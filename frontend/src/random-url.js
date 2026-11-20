export function randomEndpoint(variant='compressed',tag='',token='',origin=location.origin,json=false){
 const url=new URL(json?'/api/random':'/api/random/image',origin)
 url.searchParams.set('variant',variant==='original'?'original':'compressed')
 if(tag)url.searchParams.set('tag',tag)
 if(token)url.searchParams.set('token',token)
 return url.href
}
