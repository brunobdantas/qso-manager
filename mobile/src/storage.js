import { Capacitor } from '@capacitor/core'
import { SecureStoragePlugin } from 'capacitor-secure-storage-plugin'

// Keep the v8 storage identifiers so upgrades retain credentials and snapshots.
const DB_NAME='pu2bru-qso-manager-v8'
const STORE='datasets'
const CONNECTION_KEY='connections_v8'
const ACTIVITY_KEY='__ACTIVITY_V9__'

function db(){
  return new Promise((resolve,reject)=>{
    const req=indexedDB.open(DB_NAME,1)
    req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(STORE))req.result.createObjectStore(STORE)}
    req.onsuccess=()=>resolve(req.result)
    req.onerror=()=>reject(req.error)
  })
}

export async function saveDataset(key,value){
  const database=await db()
  return new Promise((resolve,reject)=>{
    const tx=database.transaction(STORE,'readwrite')
    tx.objectStore(STORE).put(value,key)
    tx.oncomplete=()=>resolve(value)
    tx.onerror=()=>reject(tx.error)
  })
}

export async function loadDataset(key){
  const database=await db()
  return new Promise((resolve,reject)=>{
    const tx=database.transaction(STORE,'readonly')
    const req=tx.objectStore(STORE).get(key)
    req.onsuccess=()=>resolve(req.result||{records:[],updatedAt:null,metadata:{}})
    req.onerror=()=>reject(req.error)
  })
}

export async function loadAllDatasets(keys){
  const pairs=await Promise.all(keys.map(async key=>[key,await loadDataset(key)]))
  return Object.fromEntries(pairs)
}

async function secureGet(key){
  if(!Capacitor.isNativePlatform()) return localStorage.getItem(key)
  try{
    const result=await SecureStoragePlugin.get({key})
    return result?.value||null
  }catch{return null}
}

async function secureSet(key,value){
  if(!Capacitor.isNativePlatform()){localStorage.setItem(key,value);return}
  await SecureStoragePlugin.set({key,value})
}

export async function loadConnections(){
  const raw=await secureGet(CONNECTION_KEY)
  if(!raw)return {}
  try{return JSON.parse(raw)||{}}catch{return {}}
}

export async function saveConnections(value){
  await secureSet(CONNECTION_KEY,JSON.stringify(value||{}))
  return value
}

export async function saveProviderCredentials(provider,values){
  const all=await loadConnections()
  all[provider]={...(all[provider]||{}),...values}
  await saveConnections(all)
  return all
}

export async function clearProviderCredentials(provider){
  const all=await loadConnections()
  delete all[provider]
  await saveConnections(all)
  return all
}

export async function appendActivity(kind,message,details={}){
  const current=await loadDataset(ACTIVITY_KEY)
  const rows=Array.isArray(current.records)?current.records:[]
  const item={id:`${Date.now()}-${Math.random().toString(16).slice(2)}`,at:new Date().toISOString(),kind,message,details}
  const next={records:[item,...rows].slice(0,500),updatedAt:item.at,metadata:{kind:'activity'}}
  await saveDataset(ACTIVITY_KEY,next)
  return item
}

export async function loadActivity(limit=300){
  const current=await loadDataset(ACTIVITY_KEY)
  return (current.records||[]).slice(0,limit)
}

export async function exportLocalBackup(keys){
  const datasets=await loadAllDatasets(keys)
  return {
    product:'PU2BRU QSO Manager',
    version:'9.0.0',
    createdAt:new Date().toISOString(),
    credentialsIncluded:false,
    datasets,
    activity:await loadActivity(500),
  }
}
