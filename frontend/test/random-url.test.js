import test from 'node:test'
import assert from 'node:assert/strict'
import {randomEndpoint}from '../src/random-url.js'
test('full random endpoints use current origin and safely encode tag/token',()=>{const u=new URL(randomEndpoint('original','风景 & 夏日','fixture-read-only','https://images.example:8443'));assert.equal(u.origin,'https://images.example:8443');assert.equal(u.pathname,'/api/random/image');assert.equal(u.searchParams.get('variant'),'original');assert.equal(u.searchParams.get('tag'),'风景 & 夏日');assert.equal(u.searchParams.get('token'),'fixture-read-only')})
test('public endpoints omit credentials',()=>{const u=new URL(randomEndpoint('compressed','','','http://192.0.2.10:8300'));assert.equal(u.href,'http://192.0.2.10:8300/api/random/image?variant=compressed');assert.equal(u.searchParams.has('token'),false)})
