using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Numerics;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using SoulsFormats;
using SoulsAssetPipeline.Animation;

partial class Program
{
 static readonly JsonSerializerOptions JO=new(){WriteIndented=true,IncludeFields=true};
 static readonly List<object> Issues=new();
 static string[] OnlyClips=Array.Empty<string>();
 static void Save(string p,object value){Directory.CreateDirectory(Path.GetDirectoryName(p)!);File.WriteAllText(p,JsonSerializer.Serialize(value,JO),new UTF8Encoding(false));}
 static void Log(string text)=>Console.WriteLine(text);
 static void Issue(string stage,string resource,Exception e){Issues.Add(new{stage,resource,error=e.Message});Log($"ISSUE {stage} {resource}: {e.Message}");}
 static string Name(string p)=>Path.GetFileName(p.Replace((char)92,'/'));
 static string Key(string p)=>Path.GetFileNameWithoutExtension(Name(p)).ToLowerInvariant();
 static string Sha(string p){using var f=File.OpenRead(p);return Convert.ToHexString(SHA256.HashData(f)).ToLowerInvariant();}
 static string Arg(string[] a,string n,string def=""){int i=Array.IndexOf(a,n);return i>=0&&i+1<a.Length?a[i+1]:def;}
 static void CheckId(string id){if(!Regex.IsMatch(id,@"^c[0-9]{4}$"))throw new ArgumentException("Invalid character ID: "+id);}
 static int Main(string[] args)
 {
  Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);Console.OutputEncoding=new UTF8Encoding(false);Console.InputEncoding=new UTF8Encoding(false);
  var od=Path.Combine(AppContext.BaseDirectory,"oo2core_6_win64.dll");if(File.Exists(od))System.Runtime.InteropServices.NativeLibrary.Load(od);
  Environment.SetEnvironmentVariable("PATH",AppContext.BaseDirectory+";"+Environment.GetEnvironmentVariable("PATH"));
  try
  {
   string root=Path.GetFullPath(Arg(args,"--root"));string command=args[0],output=Arg(args,"--out");
   if(command=="append-animations"){AppendAnimations(Arg(args,"--package"),root,Arg(args,"--clip-list"));return 0;}
   if(command=="resample"){ResamplePackage(Arg(args,"--package"));return 0;}
   if(command=="params"){ExportParams(root,output);return 0;}
   if(command=="npc"){NpcList(root,Arg(args,"--character"),output);return 0;}
   if(command=="metadata"){Metadata(root,Arg(args,"--package"),Arg(args,"--dsas"),Arg(args,"--npc"));return 0;}
   if(command=="weapons"){WeaponScan(root,output);return 0;}
   if(command=="part"){ExtractPart(root,Arg(args,"--part"),output);return 0;}
   if(command=="scan"){Scan(root,output);return 0;}
   string id=Arg(args,"--character"),anim=Arg(args,"--animation",id);CheckId(id);CheckId(anim);
   if(command=="analyze"){Analyze(root,id,anim,output);return 0;}
   if(command=="actions"){ListAnimations(root,id,anim,output);return 0;}
   if(command=="extract"){var list=Arg(args,"--clip-list");OnlyClips=list.Length>0?JsonSerializer.Deserialize<string[]>(File.ReadAllText(list))??[]:Arg(args,"--clips").Split(',',StringSplitOptions.RemoveEmptyEntries);if(list.Length>0&&OnlyClips.Length==0)throw new ArgumentException("没有勾选导出动作");Extract(root,id,anim,output,int.Parse(Arg(args,"--limit","0")));return 0;}
   throw new ArgumentException("Commands: scan / analyze / extract; --root --character --animation --out [--limit]");
  }catch(Exception e){Console.Error.WriteLine(e);return 1;}
 }
 static List<string> Packs(string root,string id,string ending)=>Directory.GetFiles(Path.Combine(root,"chr"),id+"*"+ending).Where(p=>Name(p).StartsWith(id+".",StringComparison.OrdinalIgnoreCase)||Name(p).StartsWith(id+"_",StringComparison.OrdinalIgnoreCase)).Order().ToList();
 static void Scan(string root,string output)
 {
  string dir=Path.Combine(root,"chr");if(!Directory.Exists(dir))throw new DirectoryNotFoundException("选择包含 chr 文件夹的游戏解包根目录");
  var rows=Directory.GetFiles(dir,"*.chrbnd.dcx").Select(p=>new{id=Name(p).Split('.')[0],model=p,modelBytes=new FileInfo(p).Length,animationPackages=Packs(root,Name(p).Split('.')[0],".anibnd.dcx").Count}).Where(r=>Regex.IsMatch(r.id,@"^c[0-9]{4}$")).OrderBy(r=>r.id).ToList();
  Save(output,new{root,characters=rows,count=rows.Count});Log($"SCAN {rows.Count} characters -> {output}");
 }
 static void Analyze(string root,string id,string anim,string output)
 {
  var packs=Packs(root,anim,".anibnd.dcx");var entries=new List<object>();int models=0,meshes=0,verts=0,bones=0;
  foreach(var f in BND4.Read(Path.Combine(root,"chr",id+".chrbnd.dcx")).Files)
  {
   entries.Add(new{package=id+".chrbnd.dcx",name=f.Name,bytes=f.Bytes.Length});
   if(f.Name.EndsWith(".flver",StringComparison.OrdinalIgnoreCase)){var fl=FLVER2.Read(f.Bytes);models++;meshes+=fl.Meshes.Count;verts+=fl.Meshes.Sum(x=>x.Vertices.Count);bones+=fl.Nodes.Count;}
  }
  int hkx=0,tae=0,compendium=0;foreach(var p in packs){foreach(var f in BND4.Read(p).Files){var n=Name(f.Name);if(Regex.IsMatch(n,@"^a[0-9]+_[0-9]+[.]hkx$",RegexOptions.IgnoreCase))hkx++;if(n.EndsWith(".tae"))tae++;if(n.EndsWith(".compendium"))compendium++;entries.Add(new{package=Name(p),name=f.Name,bytes=f.Bytes.Length});}}
  Save(output,new{character=id,animationSource=anim,models,meshes,vertices=verts,bones,animationPackages=packs.Count,hkx,tae,compendium,entries,notes=new[]{"HKX数量不是TAE事件条目数量；共用动画仍可有不同事件。",id=="c0000"?"狼模型由parts组装；完整武器/表情使用已验收配置。":"外部武器槽、动态物理、事件驱动隐藏需按角色单独验证。"}});Log($"ANALYZE {id}: {meshes} meshes / {verts} vertices / {hkx} HKX");
 }
 static object Skeleton(HKX.HKASkeleton sk)
 {
  var rows=new List<object>();for(int i=0;i<NativeData.Len(sk.Bones);i++){var tr=NativeData.Item(sk.Transforms,i);Vector4 p=(Vector4)NativeData.Field(NativeData.Field(tr,"Position"),"Vector"),q=(Vector4)NativeData.Field(NativeData.Field(tr,"Rotation"),"Vector"),s=(Vector4)NativeData.Field(NativeData.Field(tr,"Scale"),"Vector");rows.Add(new{name=NativeData.Str(NativeData.Field(NativeData.Item(sk.Bones,i),"Name")),parent=NativeData.AI(sk.ParentIndices,i),trs=new[]{p.X,p.Y,p.Z,q.X,q.Y,q.Z,q.W,s.X,s.Y,s.Z}});}return rows;
 }
 static object RootMotion(HKX h,float duration)
 {
  var reference=h.DataSection.Objects.OfType<HKX.HKADefaultAnimatedReferenceFrame>().FirstOrDefault();var data=reference==null?null:new RootMotionData(reference);bool valid=data!=null&&data.Frames.Length>0;var times=new SortedSet<float>{0,duration};if(valid&&data!.Frames.Length>1)for(int i=0;i<data.Frames.Length;i++)times.Add(Math.Clamp(i*data.Duration/(data.Frames.Length-1),0,duration));
  var player=new RootMotionDataPlayer(data);player.SyncTimeAndLocation(Vector4.Zero,0);var samples=new List<float[]>();foreach(var t in times){player.SetTime(t);var tr=NewBlendableTransform.FromRootMotionSample(player.CurrentTransform);var q=Quaternion.Normalize(tr.Rotation);samples.Add(new[]{t,tr.Translation.X,-tr.Translation.Z,tr.Translation.Y,q.W,q.X,-q.Z,q.Y});}return new{hasReference=valid,samples};
 }
 static void Extract(string root,string id,string anim,string outdir,int limit)
 {
  outdir=Path.GetFullPath(outdir);Directory.CreateDirectory(outdir);if(File.Exists(Path.Combine(outdir,"package.json")))throw new IOException("输出已有package.json，请使用新的任务目录避免覆盖。");
  var sourceFiles=new List<object>();var models=new List<string>();var taes=new List<object>();var clips=new List<object>();var textures=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);var materialNodes=new List<(string path,JsonNode node)>();
  var animpacks=Packs(root,anim,".anibnd.dcx");var modelpacks=new List<string>{Path.Combine(root,"chr",id+".chrbnd.dcx")};
  if(id=="c0000")foreach(var part in new[]{"bd_m_9000","am_m_9000","lg_m_9000","fc_m_0110","hd_m_9120"})modelpacks.Add(Path.Combine(root,"parts",part+".partsbnd.dcx"));
  modelpacks.AddRange(Packs(root,id,".texbnd.dcx"));modelpacks.AddRange(Packs(root,id,".chrtpf.dcx"));
  var archived=new HashSet<string>();
  void Archive(string p){if(!archived.Add(p))return;var dest=Path.Combine(outdir,"source_native",Path.GetRelativePath(root,p));Directory.CreateDirectory(Path.GetDirectoryName(dest)!);File.Copy(p,dest,true);var hash=Sha(p);if(Sha(dest)!=hash)throw new IOException("Copy hash mismatch "+p);sourceFiles.Add(new{source=p,file=Path.GetRelativePath(outdir,dest),bytes=new FileInfo(p).Length,sha256=hash});}
  void Tpf(byte[] bytes){var t=TPF.Read(bytes);foreach(var tx in t.Textures){var k=Key(tx.Name);string dest=Path.Combine(outdir,"textures/dds",k+".dds");Directory.CreateDirectory(Path.GetDirectoryName(dest)!);File.WriteAllBytes(dest,tx.Bytes);textures[k]=Path.GetRelativePath(outdir,dest).Replace((char)92,'/');}}
  foreach(var path in modelpacks.Distinct())
  {
   if(!File.Exists(path)){Issue("model",path,new FileNotFoundException());continue;}Archive(path);Log("MODEL "+Name(path));
   if(path.EndsWith(".chrtpf.dcx")){try{Tpf(File.ReadAllBytes(path));}catch(Exception e){Issue("texture",path,e);}continue;}
   var b=BND4.Read(path);foreach(var f in b.Files){var n=Name(f.Name);
    if(n.EndsWith(".tpf",StringComparison.OrdinalIgnoreCase)||n.EndsWith(".tpf.dcx",StringComparison.OrdinalIgnoreCase)){try{Tpf(f.Bytes);}catch(Exception e){Issue("texture",f.Name,e);}}
    if(n.EndsWith(".flver",StringComparison.OrdinalIgnoreCase)){var rel="models/"+Key(path)+"_"+n+".json";var raw=Path.Combine(outdir,"raw",Key(path),n);Directory.CreateDirectory(Path.GetDirectoryName(raw)!);File.WriteAllBytes(raw,f.Bytes);Directory.CreateDirectory(Path.Combine(outdir,"models"));NativeData.Flver(raw,Path.Combine(outdir,rel));models.Add(rel);materialNodes.Add((Path.Combine(outdir,rel),JsonNode.Parse(File.ReadAllText(Path.Combine(outdir,rel)))!));}
   }
  }
  // Resolve exact MTD texture slots; preserve every declared source slot.
  var mtdfiles=Directory.Exists(Path.Combine(root,"mtd"))?Directory.GetFiles(Path.Combine(root,"mtd"),"*.mtd",SearchOption.AllDirectories).GroupBy(Name,StringComparer.OrdinalIgnoreCase).ToDictionary(g=>g.Key,g=>g.First(),StringComparer.OrdinalIgnoreCase):new();
  var wanted=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  foreach(var pair in materialNodes){foreach(var m in pair.node["materials"]!.AsArray()){MTD? mtd=null;string mn=Name(m!["mtd"]!.GetValue<string>());if(mtdfiles.TryGetValue(mn,out var p)){try{mtd=MTD.Read(p);}catch(Exception e){Issue("mtd",mn,e);}}foreach(var t in m["textures"]!.AsArray()){string type=t!["type"]!.GetValue<string>();string original=t["path"]!.GetValue<string>();var mt=mtd?.Textures.FirstOrDefault(x=>x.Type==type);string target=!string.IsNullOrEmpty(mt?.Path)?mt.Path:original;t["resolvedName"]=Key(target);t["sourcePath"]=target;if(!string.IsNullOrEmpty(target))wanted.Add(Key(target));}}File.WriteAllText(pair.path,pair.node.ToJsonString());}
  string pool=Path.Combine(root,"mtd","textures");if(Directory.Exists(pool))foreach(var p in Directory.GetFiles(pool,"*.dds")){string key=Key(p);int i=key.IndexOf("_tex_",StringComparison.OrdinalIgnoreCase);if(i>=0)key=key[(i+5)..];if(!wanted.Contains(key)||textures.ContainsKey(key))continue;string dest=Path.Combine(outdir,"textures/dds",key+".dds");Directory.CreateDirectory(Path.GetDirectoryName(dest)!);File.Copy(p,dest,true);textures[key]=Path.GetRelativePath(outdir,dest).Replace((char)92,'/');}
  // First find the main skeleton, then decode each animation using its own binder compendium.
  byte[]? skbytes=null,skcomp=null;foreach(var p in animpacks){var b=BND4.Read(p);var sk=b.Files.FirstOrDefault(f=>Name(f.Name).Equals("skeleton.hkx",StringComparison.OrdinalIgnoreCase));if(sk!=null){skbytes=sk.Bytes;skcomp=b.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes;break;}}
  object? skeleton=null;if(skbytes!=null){var h=HKX.GenFakeFromTagFile(skbytes,skcomp);skeleton=Skeleton(h.DataSection.Objects.OfType<HKX.HKASkeleton>().First());}
  int count=0;foreach(var p in animpacks){Archive(p);var b=BND4.Read(p);var comp=b.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes??skcomp;string pack=Name(p).Replace(".anibnd.dcx","");
   foreach(var f in b.Files){string n=Name(f.Name);if(n.EndsWith(".tae")){try{taes.Add(NativeData.TaeData(SoulsFormats.TAE.Read(f.Bytes),n));}catch(Exception e){Issue("tae",n,e);}}
    bool auxiliary=id=="c0000"&&Regex.IsMatch(n,@"^a000_790[0-9]{3}[.]hkx$",RegexOptions.IgnoreCase);
    if(!Regex.IsMatch(n,@"^a[0-9]+_[0-9]+[.]hkx$",RegexOptions.IgnoreCase)||!auxiliary&&(limit>0&&count>=limit||OnlyClips.Length>0&&!OnlyClips.Contains(Key(n))&&!OnlyClips.Contains(pack+"/"+Key(n))))continue;
    try{var h=HKX.GenFakeFromTagFile(f.Bytes,comp);var an=h.DataSection.Objects.OfType<HKX.HKASplineCompressedAnimation>().FirstOrDefault();if(an==null)throw new NotSupportedException("Animation codec is not spline compressed; source retained.");var binding=h.DataSection.Objects.OfType<HKX.HKAAnimationBinding>().First();var data=new HavokAnimationData_SplineCompressed(0,n,an);var map=Enumerable.Range(0,NativeData.Len(binding.TransformTrackToBoneIndices)).Select(i=>NativeData.AI(binding.TransformTrackToBoneIndices,i)).ToArray();if(map.Length==0)throw new InvalidDataException("Empty transformTrackToBoneIndices");data.TransformTrackIndexToHkxBoneMap=map;
     var rel="animations/"+pack+"_"+Key(n)+".bin";Directory.CreateDirectory(Path.Combine(outdir,"animations"));using(var writer=new BinaryWriter(File.Create(Path.Combine(outdir,rel))))for(int frame=0;frame<data.FrameCount;frame++)for(int track=0;track<map.Length;track++){var tr=SampleNonLooping(data,track,frame);foreach(float v in new[]{tr.Translation.X,tr.Translation.Y,tr.Translation.Z,tr.Rotation.X,tr.Rotation.Y,tr.Rotation.Z,tr.Rotation.W,tr.Scale.X,tr.Scale.Y,tr.Scale.Z})writer.Write(v);}
     clips.Add(new{name=pack+"/"+Key(n),source=n,pack,frames=data.FrameCount,dt=data.FrameDuration,duration=data.Duration,map,file=rel,rootMotion=RootMotion(h,data.Duration),sampling=SamplingVersion});if(!auxiliary)count++;if(count%25==0)Log($"ANIMATION {count} {n}");
    }catch(Exception e){Issue("animation",pack+"/"+n,e);}
   }
  }
  if(skeleton==null&&clips.Count>0)Issues.Add(new{stage="skeleton",error="No skeleton.hkx; cannot map animation tracks."});
  Save(Path.Combine(outdir,"tae.json"),taes);Save(Path.Combine(outdir,"source_manifest.json"),sourceFiles);
  Save(Path.Combine(outdir,"package.json"),new{version=1,character=id,animationSource=anim,root,models,skeleton,clips,textures,missingTextures=wanted.Where(k=>!textures.ContainsKey(k)).ToArray(),issues=Issues,limited=limit>0||OnlyClips.Length>0,sourcePackages=sourceFiles.Count,axis="(x,y,z)->(x,-z,y)",fk="DSAS independent RT and Scale"});Log($"EXTRACT_DONE models={models.Count} clips={clips.Count} textures={textures.Count} issues={Issues.Count}");
 }
}



