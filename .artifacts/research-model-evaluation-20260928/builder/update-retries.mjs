import fs from 'node:fs/promises';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const root='/Users/aryankeshri/conductor/workspaces/research-and-data/jerusalem-v1';
const src=root+'/.artifacts/research-model-evaluation-20260928';
const out=root+'/outputs/research-model-evaluation-20260928';
const file=out+'/research-model-comparison.xlsx';
const backup=src+'/research-model-comparison.before-retries.xlsx';
try {await fs.copyFile(file,backup,1);} catch(e) {if(e.code!=='EEXIST')throw e;}
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(backup));
const data=JSON.parse(await fs.readFile(src+'/retry-workbook-update.json','utf8'));
const starts={},nativeLinks=[];
const last={Runs:'L',Costs:'M',Jobs:'O',Quality:'G',Failures:'F',Outputs:'F','Trace metrics':'K',Method:'B'};
const widths={Runs:[9,26,29,11,15,16,14,13,14,31,61,15],Costs:[9,16,14,16,16,19,20,17,17,14,18,16,66],Jobs:[9,28,22,15,18,19,19,17,17,19,14,15,24,24,43],Quality:[11,42,29,84,35,16,18],Failures:[12,35,26,95,55,18],Outputs:[10,29,33,27,65,105],'Trace metrics':[10,29,15,20,20,19,20,18,19,20,18],Method:[28,135]};
for(const [name,originalRows]of Object.entries(data.rows)) {
 const sheet=wb.worksheets.getItem(name);
 const end=sheet.getUsedRange().values.length;
 const start=name==='Costs'?18:end+1; starts[name]=start;
 if(name==='Costs'){
  sheet.getRange('A21:M21').copyFrom(sheet.getRange('A19:M19'),'all');
  sheet.getRange('A19:M19').clear({applyTo:'all'});
 }
 const rows=originalRows.map(r=>[...r]);
 if(name==='Jobs')for(const r of rows){r[12]=new Date(r[12]);r[13]=new Date(r[13]);}
 sheet.tables.items[0].rows.add(null,rows);
 // Bounded styling only for appended rows; original layout and cells remain intact.
 const range=sheet.getRange(`A${start}:${last[name]}${start+rows.length-1}`);
 range.format={font:{name:'Arial',size:10,color:'#24364B'},verticalAlignment:'top',wrapText:true};
 for(let i=0;i<rows.length;i++){
  const row=start+i;
  const lines=Math.max(...rows[i].map((v,k)=>String(v??'').split('\n').reduce((n,x)=>n+Math.max(1,Math.ceil(x.length/(widths[name][k]*0.85))),0)));
  sheet.getRange(`A${row}:${last[name]}${row}`).format.rowHeight=Math.max(40,lines*14+12);
  if((row-6)%2===1)sheet.getRange(`A${row}:${last[name]}${row}`).format.fill='#F2F6FA';
 }
}
const costs=wb.worksheets.getItem('Costs');
for(let row=18;row<=19;row++)costs.getRange(`K${row}`).formulas=[[`=SUM(B${row}:J${row})`]];
for(const c of 'BCDEFGHIJKL')costs.getRange(`${c}21`).formulas=[[`=SUM(${c}6:${c}19)`]];
costs.getRange('A21:M21').format={fill:'#DCE9E2',font:{name:'Arial',size:10,bold:true,color:'#183E2E'},rowHeight:30};
costs.getRange('B21:K21').setNumberFormat('$0.000000');costs.getRange('L21').setNumberFormat('0.0');
costs.getRange('B18:K19').setNumberFormat('$0.000000');costs.getRange('L18:L19').setNumberFormat('0.0');
const runs=wb.worksheets.getItem('Runs');
runs.getRange('G17:G18').formulas=[['=Costs!K18'],['=Costs!K19']];
runs.getRange('E17:F18').setNumberFormat('[m]:ss');runs.getRange('G17:G18').setNumberFormat('$0.00');runs.getRange('H17:H18').setNumberFormat('0.0');
runs.getRange('A2').values=[['13 research attempts across two seller/account pairs. Z7 adds the latest Muse xhigh quality review; Z8 records the GLM retry with different people. Recorded USD and AI Ark credits are separate. Jobs overlap; total observed includes reconciliation.']];
const jobs=wb.worksheets.getItem('Jobs'),je=starts.Jobs+data.rows.Jobs.length-1;
jobs.getRange(`D${starts.Jobs}:G${je}`).setNumberFormat('[m]:ss');jobs.getRange(`L${starts.Jobs}:L${je}`).setNumberFormat('$0.0000');jobs.getRange(`M${starts.Jobs}:N${je}`).setNumberFormat('mmm d hh:mm:ss');
const tm=wb.worksheets.getItem('Trace metrics'),te=starts['Trace metrics']+data.rows['Trace metrics'].length-1;
tm.getRange(`C${starts['Trace metrics']}:F${te}`).setNumberFormat('#,##0');tm.getRange(`G${starts['Trace metrics']}:G${te}`).setNumberFormat('[m]:ss');
const method=wb.worksheets.getItem('Method');
method.getRange('B6').values=[['13 substantive attempts: 5 Premier and 8 Zafran, plus three setup failures. Latest update adds Muse xhigh same-person quality comparison and GLM final status/artifacts. No new paid research for this report.']];
method.getRange('B7').values=[['Keep Grok 4.6 medium as quality baseline. Muse xhigh is cheaper/faster and strong on Nick, but account omissions and Vari wrong-employer attribution remain. Its retry completed all research and reconciliation after repairs; runtime differences limit model-only conclusions.']];
method.getRange('A7:B7').format.rowHeight=70;
for(const l of data.links){
 const cell=l.column+(starts[l.sheet]+l.added_row);wb.worksheets.getItem(l.sheet).getRange(cell).format.font={color:'#1767A0',underline:'single'};
 nativeLinks.push({sheet:l.sheet,cell,target:l.target});
}
await fs.writeFile(src+'/new-native-links.json',JSON.stringify(nativeLinks,null,2));
wb.recalculate();
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Updated formula check'});
await fs.writeFile(out+'/formula-check.ndjson',errors.ndjson);console.log(errors.ndjson);
console.log('new totals',costs.getRange('K21:L21').values,'starts',starts);
for(const [name,range]of [['Runs','A15:L18'],['Quality',`A${starts.Quality}:G${starts.Quality+4}`],['Costs','A16:M21']]){
 await fs.writeFile(out+'/updated-'+name+'.png',new Uint8Array(await(await wb.render({sheetName:name,range,scale:1.25,format:'png'})).arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(file);
await fs.writeFile(src+'/workbook-update-positions.json',JSON.stringify(starts,null,2));
console.log('Exported',file);
