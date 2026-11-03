"""Uploaded originals and derivatives must not contain identifying metadata."""
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import time

from PIL import Image, ImageDraw, ImageOps, PngImagePlugin
import regression as qa

MARKER = b'QA-PRIVATE-SOURCE-home-device-author-20261103'


def photo(fmt, animated=False, orientation=6):
    image = Image.new('RGB', (64, 48), '#678fc2')
    ImageDraw.Draw(image).rectangle((0, 0, 25, 15), fill='#ff5500')
    exif = Image.Exif()
    exif[274] = orientation
    exif[271] = MARKER.decode()
    exif[272] = MARKER.decode()
    exif[315] = MARKER.decode()
    exif[306] = '2020:01:02 03:04:05'
    exif[34853] = {1:'N',2:(31.,12.,0.),3:'E',4:(121.,24.,0.)}
    out = io.BytesIO()
    kwargs = {}
    if fmt in ('JPEG','PNG','WEBP','AVIF'):
        kwargs.update(exif=exif,icc_profile=MARKER)
    if fmt == 'AVIF':
        kwargs.update(max_threads=1,speed=8)
    if fmt in ('WEBP','AVIF'):
        kwargs['xmp'] = b'<x:xmpmeta>'+MARKER+b'</x:xmpmeta>'
    if fmt=='JPEG':
        kwargs.update(quality=91,comment=MARKER,progressive=True)
    if fmt=='PNG':
        text = PngImagePlugin.PngInfo()
        text.add_text('Author',MARKER.decode())
        text.add_text('Source',MARKER.decode(),zip=True)
        text.add_itxt('XML:com.adobe.xmp',MARKER.decode())
        kwargs['pnginfo']=text
    if fmt=='GIF':
        kwargs['comment']=MARKER
    if animated:
        second=Image.new('RGB',(64,48),'#edb287')
        kwargs.update(save_all=True,append_images=[second],duration=[90,160],loop=2)
    image.save(out,fmt,**kwargs)
    value=out.getvalue()
    if fmt=='JPEG':
        # Include IPTC, XMP and a comment after the final scan, not just EXIF
        # preceding the first scan. Both must be removed without pixel loss.
        app13=b'Photoshop 3.0\0'+MARKER
        xmp=b'http://ns.adobe.com/xap/1.0/\0'+MARKER
        value=value[:2]+b'\xff\xed'+struct.pack('>H',len(app13)+2)+app13+b'\xff\xe1'+struct.pack('>H',len(xmp)+2)+xmp+value[2:]
        comment=b'\xff\xfe'+struct.pack('>H',len(MARKER)+2)+MARKER
        value=value[:-2]+comment+value[-2:]
    # A filename, GPS record, or arbitrary editor payload appended outside the
    # image must not survive simply because a decoder ignores trailing bytes.
    return value+MARKER


def inspect(value):
    with Image.open(io.BytesIO(value)) as im:
        count=getattr(im,'n_frames',1)
        frames=[]
        durations=[]
        for i in range(count):
            im.seek(i); im.load()
            frames.append(ImageOps.exif_transpose(im).convert('RGBA').tobytes())
            durations.append(im.info.get('duration',0))
            assert not (set(im.getexif())-{274}),dict(im.getexif())
            assert not any(im.info.get(k) for k in ('xmp','XML:com.adobe.xmp','comment','icc_profile','Author','Source')),im.info
        return im.format, count, frames, durations


def suite(data):
    proc,log,call,env=qa.run(data)
    try:
        token=call('POST','/api/auth/login',{'username':'owner','password':'qa-pass-123'})[1]['token']
        formats=[('JPEG','jpg',False),('PNG','png',False),('WEBP','webp',False),('GIF','gif',True),('BMP','bmp',False),('PNG','png',True),('WEBP','webp',True)]
        if 'AVIF' in Image.registered_extensions().values():
            formats += [('AVIF','avif',False),('AVIF','avif',True)]
        for fmt,ext,animated in formats:
            name=f'{fmt}-'+('animated' if animated else 'static')
            payload=photo(fmt,animated,1 if fmt=="AVIF" and animated else 6)
            source=Image.open(io.BytesIO(payload))
            expected_count=getattr(source,'n_frames',1)
            expected_size=ImageOps.exif_transpose(source).size
            source_frames=[]
            for i in range(expected_count):
                source.seek(i); source_frames.append(ImageOps.exif_transpose(source).convert('RGBA').tobytes())
            source.close()
            for mode in ('multipart','resumable'):
                if mode=='resumable':
                    body={'clientId':hashlib.sha256((name+mode).encode()).hexdigest()[:32],'filename':'PRIVATE-home-device.'+ext,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
                    status,row=call('POST','/api/uploads',body,token)
                    assert status==200,row
                    status,_=call('PUT','/api/uploads/'+row['id']+'/chunk',payload,token,{'Upload-Offset':'0','X-Chunk-SHA256':body['sha256']})
                    assert status==200
                    call('POST','/api/uploads/'+row['id']+'/complete',token=token)
                    deadline=time.monotonic()+float(__import__('os').environ.get('QA_REQUEST_TIMEOUT','60'))
                    while time.monotonic()<deadline:
                        receipt=call('GET','/api/uploads/'+row['id'],token=token)[1]
                        if receipt['status'] in ('done','failed'): break
                        time.sleep(.1)
                    assert receipt['status']=='done',receipt
                    item=receipt['item']
                    qa.check(name+' resume checksum stays tied to original transfer',receipt['sha256']==body['sha256'] and receipt['size']==len(payload))
                else:
                    b,h=qa.multipart([('files','PRIVATE-home-device.'+ext,payload)])
                    result=call('POST','/api/upload',b,token,h)[1]['results'][0]
                    assert result['ok'],result
                    item=result['item']
                status,original=call('GET',item['url'],raw=True)
                qa.check(name+' '+mode+' original removes source records',status==200 and MARKER not in original and b'PRIVATE-home-device' not in original)
                out_fmt,count,frames,durations=inspect(original)
                qa.check(name+' '+mode+' original retains format, dimensions and frames',out_fmt==fmt and count==expected_count and (item['width'],item['height'])==expected_size)
                qa.check(name+' '+mode+' stored size and public filename describe clean file',item['size']==len(original) and 'PRIVATE-home-device' not in item['origName'])
                if fmt in ('JPEG','PNG','WEBP','GIF'):
                    qa.check(name+' '+mode+' original pixels are not recompressed',frames==source_frames)
                if fmt=='GIF':
                    qa.check('GIF retains frame timing',durations==[90,160])
                for key in ('thumb','compressed'):
                    if not item[key]: continue
                    status,version=call('GET',item[key],raw=True)
                    inspect(version)
                    qa.check(name+' '+mode+' '+key+' removes metadata',status==200 and MARKER not in version)
        (data/'uploads'/'local-metadata.png').write_bytes(photo('PNG'))
        hidden=data/'uploads'/'.avif-clean-interrupted'
        hidden.mkdir();(hidden/'0.png').write_bytes(photo('PNG'))
        call('POST','/api/admin/local/import',token=token)
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            job=call('GET','/api/admin/local/status',token=token)[1]
            if not job['running']: break
            time.sleep(.1)
        local=next(x for x in call('GET','/api/images?limit=100',token=token)[1]['items'] if x['key']=='local-metadata.png')
        clean=call('GET',local['url'],raw=True)[1]
        inspect(clean)
        qa.check('new local imports also clean metadata before indexing',MARKER not in clean and local['size']==len(clean) and job['imported']==1)
        count=call('GET','/api/images')[1]['total']
        unsafe=io.BytesIO();Image.new('RGB',(10,10)).save(unsafe,'TIFF')
        b,h=qa.multipart([('files','unsupported.jpg',unsafe.getvalue())])
        result=call('POST','/api/upload',b,token,h)[1]['results'][0]
        qa.check('failure to safely clean an image never publishes the original',not result['ok'] and call('GET','/api/images')[1]['total']==count)
        print(f'\n{qa.passed} metadata HTTP checks passed',flush=True)
    finally:
        proc.terminate();proc.wait(timeout=20);log.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='metadata-',dir=qa.TEMP) as tmp:suite(Path(tmp))

