using System.Text.Json;
using System.Text.Json.Nodes;
using SoulsFormats;

partial class Program
{
 static void Metadata(string root,string folder,string dsas,string npc)
 {
  var packagePath=Path.Combine(folder,"package.json");var pkg=JsonNode.Parse(File.ReadAllText(packagePath))!;
  var mtdDir=Path.Combine(root,"mtd");
  var mtds=Directory.GetFiles(mtdDir,"*.mtd",SearchOption.AllDirectories).GroupBy(Name,StringComparer.OrdinalIgnoreCase).ToDictionary(g=>g.Key,g=>g.First(),StringComparer.OrdinalIgnoreCase);
  foreach(var rel in pkg["models"]!.AsArray())
  {
   var file=Path.Combine(folder,rel!.GetValue<string>());var model=JsonNode.Parse(File.ReadAllText(file))!;
   foreach(var mat in model["materials"]!.AsArray())
   {
    if(!mtds.TryGetValue(Name(mat!["mtd"]!.GetValue<string>()),out var source))continue;
    var mtd=MTD.Read(source);mat["shader"]=Key(mtd.ShaderPath);
    mat["mtd_source_sha256"]=Sha(source);
    var configDir=Path.Combine(dsas,"ShaderConfig","SDT");
    var config=Directory.Exists(configDir)?Directory.GetFiles(configDir,"*.json").FirstOrDefault(f=>Key(f).Equals(Key(mtd.ShaderPath),StringComparison.OrdinalIgnoreCase)):null;
    if(config!=null){mat["shader_config"]=JsonNode.Parse(File.ReadAllText(config));mat["shader_config_sha256"]=Sha(config);}
    foreach(var tex in mat["textures"]!.AsArray())
    {
     var tx=mtd.Textures.FirstOrDefault(t=>t.Type==tex!["type"]!.GetValue<string>());if(tx==null)continue;
     var sc=mat["shader_config"]?["SamplerConfigs"]?.AsArray().FirstOrDefault(s=>s?["Name"]?.GetValue<string>()==tx.Type);
     int group=sc?["UVGroup"]?.GetValue<int>()??0;
     float sx=1,sy=1; if(tx.UnkFloats.Count==2){if(tx.UnkFloats[0]!=0)sx=tx.UnkFloats[0];if(tx.UnkFloats[1]!=0)sy=tx.UnkFloats[1];}
     var param=mtd.Params.FirstOrDefault(x=>x.Name==$"group_{group+1}_CommonUV-UVParam");
     if(param?.Value is float[] uv&&uv.Length>=2){sx*=uv[0];sy*=uv[1];}
     tex!["uv_scale"]=new JsonArray(sx,sy);
     if(sc!=null){tex["sampler"]=sc.DeepClone();}
    }
   }
   File.WriteAllText(file,model.ToJsonString());
  }
  string id=pkg["character"]!.GetValue<string>();
  if(id.StartsWith("c")&&id!="c0000")
  {
   var source=Path.Combine(root,"param/gameparam/gameparam.parambnd.dcx");var bnd=BND4.Read(source);var f=bnd.Files.Single(f=>Name(f.Name).Equals("NpcParam.param",StringComparison.OrdinalIgnoreCase));var param=PARAM.Read(f.Bytes);var options=NpcOptions(param,f.Bytes,id);
   JsonNode? selected=string.IsNullOrWhiteSpace(npc)?options.FirstOrDefault():options.FirstOrDefault(x=>x!["id"]!.ToString()==npc);
   if(!string.IsNullOrWhiteSpace(npc)&&selected==null)throw new ArgumentException("NPC PARAM ID not found for "+id+": "+npc);
   pkg["npcAppearance"]=new JsonObject{["source"]=source,["source_sha256"]=Sha(source),["selection"]=string.IsNullOrWhiteSpace(npc)?"DSAS first matching NpcParam ID":"explicit NpcParam ID",["selected"]=selected?.DeepClone(),["options"]=options};
  }
  File.WriteAllText(packagePath,pkg.ToJsonString());Log("METADATA_DONE shader sampler UVs + NPC appearance "+id);
 }
 static JsonArray NpcOptions(PARAM param,byte[] bytes,string id)
 {
  var options=new JsonArray();int chr=int.Parse(id[1..]);
   foreach(var row in param.Rows.Where(r=>(r.ID%100000000)/10000==chr).OrderBy(r=>r.ID))
   {
    long offset=Convert.ToInt64(NativeData.Field(row,"DataOffset"));var raw=bytes.AsSpan((int)offset,(int)param.DetectedSize!).ToArray();if(raw.Length<0x154)continue;var mask=new JsonArray();for(int i=0;i<32;i++){int off=i<16?0x14E+i/8:0x152+(i-16)/8;mask.Add((raw[off]&(1<<(i%8)))!=0);}
    options.Add(new JsonObject{["id"]=row.ID,["name"]=row.Name,["drawMask"]=mask,["row_sha256"]=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(raw)).ToLowerInvariant()});
   }
return options;
 }
 static void NpcList(string root,string id,string output)
 {
  CheckId(id);var bnd=BND4.Read(Path.Combine(root,"param/gameparam/gameparam.parambnd.dcx"));var f=bnd.Files.Single(f=>Name(f.Name).Equals("NpcParam.param",StringComparison.OrdinalIgnoreCase));Save(output,NpcOptions(PARAM.Read(f.Bytes),f.Bytes,id));
 }

}
