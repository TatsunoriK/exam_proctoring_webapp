import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parse} from '@babel/parser';
import traverseModule from '@babel/traverse';
const traverse=traverseModule.default || traverseModule;
test('all JSX components used by exam UI are declared or imported',()=>{
 const source=readFileSync(new URL('./ui.tsx',import.meta.url),'utf8');
 const ast=parse(source,{sourceType:'module',plugins:['typescript','jsx']});
 const missing=new Set();
 traverse(ast,{JSXOpeningElement(path){const name=path.node.name;if(name.type==='JSXIdentifier'&&/^[A-Z]/.test(name.name)&&!path.scope.hasBinding(name.name))missing.add(name.name)}});
 assert.deepEqual([...missing],[]);
});
