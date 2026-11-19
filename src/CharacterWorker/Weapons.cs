using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using SoulsFormats;
using SoulsAssetPipeline.Animation;
partial class Program
{
 static HKX ReadHkxCompatible(byte[] bytes,byte[]? comp)
 {
  try{return HKX.GenFakeFromTagFile(bytes,comp);}catch(Exception first){foreach(var kind in new[]{HKX.HKXVariation.HKXDS1,HKX.HKXVariation.HKXDS3,HKX.HKXVariation.HKXBloodBorne})foreach(bool hotfix in new[]{true,false}){try{return HKX.Read(bytes,kind,isDS1RAnimHotfix:hotfix);}catch{}}throw new InvalidDataException("Tagfile and legacy HKX parsers failed: "+first.Message,first);}
 }
 static void ExportParams(string root,string outdir)
 {
  Directory.CreateDirectory(outdir);var b=BND4.Read(Path.Combine(root,"param/gameparam/gameparam.parambnd.dcx"));
  foreach(var name in new[]{"EquipParamWeapon.param","WepAbsorpPosParam.param"}){var f=b.Files.Single(x=>Name(x.Name).Equals(name,StringComparison.OrdinalIgnoreCase));var p=PARAM.Read(f.Bytes);var rows=new List<object>();foreach(var r in p.Rows){long offset=Convert.ToInt64(NativeData.Field(r,"DataOffset"));var raw=f.Bytes.AsSpan((int)offset,(int)p.DetectedSize!).ToArray();rows.Add(new{id=r.ID,name=r.Name,raw=Convert.ToHexString(raw)});}Save(Path.Combine(outdir,name+".json"),rows);}
 }
 static void WeaponScan(string root,string output)
 {
  var rows=Directory.GetFiles(Path.Combine(root,"parts"),"wp*.partsbnd.dcx").Order().Select(p=>new{id=Name(p).Replace(".partsbnd.dcx",""),bytes=new FileInfo(p).Length,path=p}).ToArray();
  Save(output,new{root,weapons=rows,count=rows.Length});Log($"WEAPONS {rows.Length}");
 }
 static void ExtractPart(string root,string id,string outdir)
 {
  if(!Regex.IsMatch(id,@"^wp_[a-z]_[0-9]{4}(_[a-z])?$",RegexOptions.IgnoreCase))throw new ArgumentException("Invalid weapon part ID");
  outdir=Path.GetFullPath(outdir);Directory.CreateDirectory(outdir);if(File.Exists(Path.Combine(outdir,"package.json")))throw new IOException("Output already exists");
  var path=Path.Combine(root,"parts",id+".partsbnd.dcx");var b=BND4.Read(path);var models=new List<string>();var textures=new Dictionary<string,string>();var motions=new Dictionary<string,object>();var native=new List<object>();
  Directory.CreateDirectory(Path.Combine(outdir,"source_native"));File.Copy(path,Path.Combine(outdir,"source_native",Name(path)),false);native.Add(new{source=path,file="source_native/"+Name(path),sha256=Sha(path)});
  foreach(var f in b.Files)
  {
   string n=Name(f.Name);var raw=Path.Combine(outdir,"raw",n);Directory.CreateDirectory(Path.GetDirectoryName(raw)!);File.WriteAllBytes(raw,f.Bytes);
   if(n.EndsWith(".flver",StringComparison.OrdinalIgnoreCase)){string rel="models/"+n+".json";Directory.CreateDirectory(Path.Combine(outdir,"models"));NativeData.Flver(raw,Path.Combine(outdir,rel));models.Add(rel);}
   if(n.EndsWith(".tpf",StringComparison.OrdinalIgnoreCase))foreach(var tx in TPF.Read(f.Bytes).Textures){string k=Key(tx.Name),rel="textures/dds/"+k+".dds";Directory.CreateDirectory(Path.Combine(outdir,"textures/dds"));File.WriteAllBytes(Path.Combine(outdir,rel),tx.Bytes);textures[k]=rel;}
   if(n.EndsWith(".anibnd",StringComparison.OrdinalIgnoreCase)||n.EndsWith(".anibnd.dcx",StringComparison.OrdinalIgnoreCase)){try{motions[Key(n)]=ReadPartMotion(f.Bytes);}catch(Exception e){Issue("weapon_animation",n,e);}}
  }
  var wanted=new HashSet<string>();var mtdDir=Path.Combine(root,"mtd");var mtds=Directory.Exists(mtdDir)?Directory.GetFiles(mtdDir,"*.mtd",SearchOption.AllDirectories).GroupBy(Name,StringComparer.OrdinalIgnoreCase).ToDictionary(g=>g.Key,g=>g.First(),StringComparer.OrdinalIgnoreCase):new();
  foreach(var rel in models){var node=JsonNode.Parse(File.ReadAllText(Path.Combine(outdir,rel)))!;foreach(var m in node["materials"]!.AsArray()){MTD? mt=null;if(mtds.TryGetValue(Name(m!["mtd"]!.GetValue<string>()),out var mp))mt=MTD.Read(mp);foreach(var t in m["textures"]!.AsArray()){string type=t!["type"]!.GetValue<string>();string orig=t["path"]!.GetValue<string>();var tt=mt?.Textures.FirstOrDefault(x=>x.Type==type);string target=string.IsNullOrEmpty(tt?.Path)?orig:tt.Path;var key=Key(target);if(!textures.ContainsKey(key)&&id.EndsWith("_m")&&textures.ContainsKey(key+"_m")){t["resolutionRule"]="matching parts suffix _m";key+="_m";}t["resolvedName"]=key;if(key.Length>0)wanted.Add(key);}}File.WriteAllText(Path.Combine(outdir,rel),node.ToJsonString());}
  var pool=Path.Combine(root,"mtd/textures");if(Directory.Exists(pool))foreach(var p in Directory.GetFiles(pool,"*.dds")){var key=Key(p);int i=key.IndexOf("_tex_");if(i>=0)key=key[(i+5)..];if(wanted.Contains(key)&&!textures.ContainsKey(key)){var rel="textures/dds/"+key+".dds";Directory.CreateDirectory(Path.Combine(outdir,"textures/dds"));File.Copy(p,Path.Combine(outdir,rel),true);textures[key]=rel;}}
  foreach(var common in new[]{"systex.tpf.dcx","decaltex.tpf.dcx"}){var source=Path.Combine(root,"other",common);if(!File.Exists(source))continue;bool used=false;foreach(var tx in TPF.Read(source).Textures){var key=Key(tx.Name);if(!wanted.Contains(key)||textures.ContainsKey(key))continue;var rel="textures/dds/"+key+".dds";File.WriteAllBytes(Path.Combine(outdir,rel),tx.Bytes);textures[key]=rel;used=true;}if(used){File.Copy(source,Path.Combine(outdir,"source_native",common),true);native.Add(new{source,file="source_native/"+common,sha256=Sha(source)});}}
  // A part can reference a texture stored in a sibling part. Resolve exact names only.
  var missing=wanted.Where(k=>!textures.ContainsKey(k)&&!k.StartsWith("systex_")&&!k.StartsWith("dummy")).ToHashSet();
  if(missing.Count>0)foreach(var other in Directory.GetFiles(Path.Combine(root,"parts"),"wp*.partsbnd.dcx").Order()){if(missing.Count==0)break;if(other==path)continue;try{bool used=false;foreach(var file in BND4.Read(other).Files.Where(f=>f.Name.EndsWith(".tpf",StringComparison.OrdinalIgnoreCase)))foreach(var tx in TPF.Read(file.Bytes).Textures){var k=Key(tx.Name);if(!missing.Remove(k))continue;var rel="textures/dds/"+k+".dds";File.WriteAllBytes(Path.Combine(outdir,rel),tx.Bytes);textures[k]=rel;used=true;}if(used){File.Copy(other,Path.Combine(outdir,"source_native",Name(other)),true);native.Add(new{source=other,file="source_native/"+Name(other),sha256=Sha(other)});}}catch(Exception e){Log("SIBLING_TEXTURE_SKIP "+Name(other)+" "+e.Message);}}
  Save(Path.Combine(outdir,"weapon_motion.json"),motions);Save(Path.Combine(outdir,"source_manifest.json"),native);
  Save(Path.Combine(outdir,"package.json"),new{version=1,character=id,assetType="weapon",animationSource=id,root,models,skeleton=Array.Empty<object>(),clips=Array.Empty<object>(),textures,missingTextures=wanted.Where(k=>!textures.ContainsKey(k)).ToArray(),issues=Issues,limited=false,sourcePackages=1});
  Log($"PART_DONE {id}: {models.Count} models, {motions.Count} motion containers, {textures.Count} textures");
 }
 static object ReadPartMotion(byte[] bytes)
 {
  var b=BND4.Read(bytes);var taes=b.Files.Where(f=>f.Name.EndsWith(".tae")).Select(f=>NativeData.TaeData(SoulsFormats.TAE.Read(f.Bytes),Name(f.Name))).ToArray();var cp=b.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes;var sf=b.Files.FirstOrDefault(f=>f.ID==1000000||Name(f.Name).Equals("skeleton.hkx",StringComparison.OrdinalIgnoreCase));if(sf==null)return new{taes,bones=Array.Empty<object>(),animations=Array.Empty<object>()};
  var h=ReadHkxCompatible(sf.Bytes,cp);var sk=h.DataSection.Objects.OfType<HKX.HKASkeleton>().First();var bones=new List<object>();
  for(int i=0;i<NativeData.Len(sk.Bones);i++){var tr=NativeData.Item(sk.Transforms,i);float[] V(object v){var x=(System.Numerics.Vector4)NativeData.Field(v,"Vector");return new[]{x.X,x.Y,x.Z,x.W};}bones.Add(new{name=NativeData.Str(NativeData.Field(NativeData.Item(sk.Bones,i),"Name")),parent=NativeData.AI(sk.ParentIndices,i),t=V(NativeData.Field(tr,"Position")),q=V(NativeData.Field(tr,"Rotation")),s=V(NativeData.Field(tr,"Scale"))});}
  foreach(var item in b.Files)Log($"WEAPON_ENTRY {item.ID} {Name(item.Name)}");var animations=new List<object>();foreach(var f in b.Files.Where(f=>Regex.IsMatch(Name(f.Name),@"^a[0-9]+_[0-9]+(_[0-9]+)?[.]hkx$",RegexOptions.IgnoreCase))){var hh=ReadHkxCompatible(f.Bytes,cp);var an=hh.DataSection.Objects.OfType<HKX.HKASplineCompressedAnimation>().First();var binding=hh.DataSection.Objects.OfType<HKX.HKAAnimationBinding>().First();var data=new HavokAnimationData_SplineCompressed(0,Name(f.Name),an);var map=Enumerable.Range(0,NativeData.Len(binding.TransformTrackToBoneIndices)).Select(i=>NativeData.AI(binding.TransformTrackToBoneIndices,i)).ToArray();data.TransformTrackIndexToHkxBoneMap=map;var frames=new List<float[][]>();for(int fr=0;fr<data.FrameCount;fr++){var vals=new List<float[]>();for(int t=0;t<map.Length;t++){var x=SampleNonLooping(data,t,fr);vals.Add(new[]{x.Translation.X,x.Translation.Y,x.Translation.Z,x.Rotation.X,x.Rotation.Y,x.Rotation.Z,x.Rotation.W,x.Scale.X,x.Scale.Y,x.Scale.Z});}frames.Add(vals.ToArray());}animations.Add(new{name=Key(f.Name),duration=data.Duration,frameDuration=data.FrameDuration,map,frames,sampling=SamplingVersion});}
  return new{taes,bones,animations};
 }
}





