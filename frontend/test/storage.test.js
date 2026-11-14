import test from 'node:test'
import assert from 'node:assert/strict'
import { readStorage, writeStorage, removeStorage } from '../src/storage.js'
test('storage getter and operation failures are recoverable', () => {
 Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw new Error('denied')}})
 assert.equal(readStorage('localStorage','key','fallback'),'fallback')
 assert.equal(writeStorage('localStorage','key','value'),false)
 assert.equal(removeStorage('localStorage','key'),false)
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem(){throw Error()},setItem(){throw Error()},removeItem(){throw Error()}}})
 assert.equal(readStorage('localStorage','key'),'')
 assert.equal(writeStorage('localStorage','key','value'),false)
 assert.equal(removeStorage('localStorage','key'),false)
})
