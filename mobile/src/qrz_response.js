function decodeHtmlEntities(value){
  return String(value??'')
    .replace(/&#x([0-9a-f]+);/gi,(_,hex)=>{
      const code=Number.parseInt(hex,16)
      return Number.isFinite(code)?String.fromCodePoint(code):_
    })
    .replace(/&#(\d+);/g,(_,dec)=>{
      const code=Number.parseInt(dec,10)
      return Number.isFinite(code)?String.fromCodePoint(code):_
    })
    .replace(/&lt;/gi,'<')
    .replace(/&gt;/gi,'>')
    .replace(/&quot;/gi,'"')
    .replace(/&apos;|&#39;/gi,"'")
    .replace(/&amp;/gi,'&')
}

function decodeFormValue(value){
  const text=String(value??'')
  try{return decodeURIComponent(text.replace(/\+/g,' '))}
  catch{return text}
}

export function decodeQRZAdif(value){
  let text=decodeHtmlEntities(value)
  for(let i=0;i<3;i++){
    // Literal ADIF must stay literal. Decoding it as form data would turn
    // legitimate '+' values (for example RST +06) into spaces.
    if(text.includes('<'))break
    if(!text.includes('%')&&!/&(?:lt|gt|amp|quot|apos|#\d+|#x[0-9a-f]+);/i.test(text))break
    const decoded=decodeHtmlEntities(decodeFormValue(text))
    if(decoded===text)break
    text=decoded
  }
  return text
}

export function parseQRZResponse(rawValue){
  const raw=String(rawValue??'')
  const params=new URLSearchParams(raw)
  const parsed={}
  for(const [key,value] of params.entries())parsed[key.toUpperCase()]=value

  // QRZ may return ADIF literally or form-encoded (sometimes more than once).
  // Extract it from the raw response before the generic query parser can
  // reinterpret '&' or '+' characters that belong to the ADIF payload.
  const match=raw.match(/(?:^|&)ADIF=([\s\S]*?)(?=&(?:RESULT|REASON|LOGIDS?|COUNT|DATA)=|$)/i)
  if(match)parsed.ADIF=decodeQRZAdif(match[1])
  else if(parsed.ADIF!=null)parsed.ADIF=decodeQRZAdif(parsed.ADIF)

  return parsed
}
