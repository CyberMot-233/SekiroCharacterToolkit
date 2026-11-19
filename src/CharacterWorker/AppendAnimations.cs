using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using SoulsFormats;
using SoulsAssetPipeline.Animation;
partial class Program
{
 static void AppendAnimations(string folder,string root,string list)
 {
  folder=Path.GetFullPath(folder);var path=Path.Combine(folder,"package.json");var pkg=JsonNode.Parse(File.ReadAllText(path))!;
  var wanted=JsonSerializer.Deserialize<string[]>(File.ReadAllText(list))??[];
  if(wanted.Length==0||wanted.Distinct().Count()!=wanted.Length)throw new ArgumentException("请选择不重复的动作列表");
  foreach(var name in wanted)if(!Regex.IsMatch(name,@"^c[0-9]{4}[^/\\]*/a[0-9]+_[0-9]+$"))throw new ArgumentException("无效动作名称："+name);
  var packNames=wanted.Select(n=>n.Split('/')[0]).Distinct().ToArray();var packs=new Dictionary<string,BND4>();
  string Source(string pack){var local=Path.Combine(folder,"source_native/chr",pack+".anibnd.dcx");return File.Exists(local)?local:Path.Combine(root,"chr",pack+".anibnd.dcx");}
  var anim=pkg["animationSource"]!.ToString();var skeletonPack=BND4.Read(Source(anim));
  var skeletonFile=skeletonPack.Files.Single(f=>Name(f.Name).Equals("skeleton.hkx",StringComparison.OrdinalIgnoreCase));
  var fallback=skeletonPack.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes;
  var sk=HKX.GenFakeFromTagFile(skeletonFile.Bytes,fallback).DataSection.Objects.OfType<HKX.HKASkeleton>().Single();
  var decoded=JsonSerializer.SerializeToNode(Skeleton(sk),JO);
  if(!JsonNode.DeepEquals(decoded,pkg["skeleton"]))throw new InvalidDataException("动画源骨架与已有提取包不一致；未修改目标文件");
  var clips=pkg["clips"]!.AsArray();var taes=JsonNode.Parse(File.ReadAllText(Path.Combine(folder,"tae.json")))!.AsArray();
  var records=new List<object>();var requested=new HashSet<string>(wanted);
  foreach(var pack in packNames)
  {
   var b=BND4.Read(Source(pack));packs[pack]=b;var comp=b.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes??fallback;
   foreach(var f in b.Files.Where(f=>Name(f.Name).EndsWith(".tae",StringComparison.OrdinalIgnoreCase)))
   {
    var value=JsonSerializer.SerializeToNode(NativeData.TaeData(SoulsFormats.TAE.Read(f.Bytes),Name(f.Name)),JO)!;var old=taes.FirstOrDefault(t=>t!["name"]!.ToString()==Name(f.Name));if(old!=null)taes.Remove(old);taes.Add(value);
   }
   foreach(var f in b.Files)
   {
    var key=Key(f.Name);var name=pack+"/"+key;
    bool auxiliary=pkg["character"]!.ToString()=="c0000"&&Regex.IsMatch(Name(f.Name),@"^a000_790[0-9]{3}[.]hkx$",RegexOptions.IgnoreCase);
    if(!requested.Contains(name)&&!auxiliary)continue;
    var h=HKX.GenFakeFromTagFile(f.Bytes,comp);var data=new HavokAnimationData_SplineCompressed(0,Name(f.Name),h.DataSection.Objects.OfType<HKX.HKASplineCompressedAnimation>().Single());
    var binding=h.DataSection.Objects.OfType<HKX.HKAAnimationBinding>().Single();var map=Enumerable.Range(0,NativeData.Len(binding.TransformTrackToBoneIndices)).Select(i=>NativeData.AI(binding.TransformTrackToBoneIndices,i)).ToArray();
    if(map.Length==0||map.Any(i=>i<0||i>=pkg["skeleton"]!.AsArray().Count))throw new InvalidDataException("动画轨道骨骼映射无效："+name);
    var rel="animations/"+pack+"_"+key+".bin";var dest=Path.Combine(folder,rel);Directory.CreateDirectory(Path.GetDirectoryName(dest)!);var pending=dest+".append_pending";
    using(var w=new BinaryWriter(File.Create(pending)))for(int frame=0;frame<data.FrameCount;frame++)for(int track=0;track<map.Length;track++)foreach(var v in Values(SampleNonLooping(data,track,frame)))w.Write(v);
    File.Move(pending,dest,true);var old=clips.FirstOrDefault(c=>c!["name"]!.ToString()==name);bool replaced=old!=null;if(old!=null)clips.Remove(old);
    clips.Add(JsonSerializer.SerializeToNode(new{name,source=Name(f.Name),pack,frames=data.FrameCount,dt=data.FrameDuration,duration=data.Duration,map,file=rel,rootMotion=RootMotion(h,data.Duration),sampling=SamplingVersion},JO));
    records.Add(new{name,replaced,auxiliary});Log("APPEND_SAMPLED "+name);requested.Remove(name);
   }
  }
  if(requested.Count>0)throw new InvalidDataException("源包中缺少动作："+string.Join(", ",requested));
  File.WriteAllText(path,pkg.ToJsonString(JO));File.WriteAllText(Path.Combine(folder,"tae.json"),taes.ToJsonString(JO));
  Save(Path.Combine(folder,"append_sampling.json"),new{passed=true,records});
 }
}
