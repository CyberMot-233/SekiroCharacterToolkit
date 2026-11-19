using System.Numerics;
using System.Text.Json.Nodes;
using SoulsFormats;
using SoulsAssetPipeline.Animation;

partial class Program
{
 const string SamplingVersion = "nonloop-block-end-v2";
 // SAP RC6.1 GetBlock wraps frame % (FrameCount-1), even with looping disabled.
 // Sample the explicit block and local knot time; the terminal knot must not wrap.
 static NewBlendableTransform SampleNonLooping(HavokAnimationData_SplineCompressed data,int track,float frame)
 {
  if(data.FrameCount<1||data.Tracks.Count==0||data.NumFramesPerBlock<2)throw new InvalidDataException("Invalid spline dimensions");
  frame=Math.Clamp(frame,0,data.FrameCount-1);
  int span=data.NumFramesPerBlock-1;
  int block=Math.Min((int)MathF.Floor(frame/span),data.Tracks.Count-1);
  float local=frame-block*span;
  var t=data.Tracks[block][track];var x=NewBlendableTransform.Identity;
  if(t.SplinePosition!=null)x.Translation=new Vector3(t.SplinePosition.GetValueX(local,data.FrameCount)??0,t.SplinePosition.GetValueY(local,data.FrameCount)??0,t.SplinePosition.GetValueZ(local,data.FrameCount)??0);
  else x.Translation=new Vector3(t.Mask.PositionTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticX)?t.StaticPosition.X:0,t.Mask.PositionTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticY)?t.StaticPosition.Y:0,t.Mask.PositionTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticZ)?t.StaticPosition.Z:0);
  x.Rotation=t.SplineRotation!=null?t.SplineRotation.GetValue(local,data.FrameCount):t.HasStaticRotation?t.StaticRotation:Quaternion.Identity;
  if(t.SplineScale!=null)x.Scale=new Vector3(t.SplineScale.GetValueX(local,data.FrameCount)??1,t.SplineScale.GetValueY(local,data.FrameCount)??1,t.SplineScale.GetValueZ(local,data.FrameCount)??1);
  else x.Scale=new Vector3(t.Mask.ScaleTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticX)?t.StaticScale.X:1,t.Mask.ScaleTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticY)?t.StaticScale.Y:1,t.Mask.ScaleTypes.Contains(SplineCompressedAnimation.FlagOffset.StaticZ)?t.StaticScale.Z:1);
  if(float.IsNaN(x.Scale.X))x.Scale.X=1;if(float.IsNaN(x.Scale.Y))x.Scale.Y=1;if(float.IsNaN(x.Scale.Z))x.Scale.Z=1;
  return x;
 }
 static float[] Values(NewBlendableTransform x)=>new[]{x.Translation.X,x.Translation.Y,x.Translation.Z,x.Rotation.X,x.Rotation.Y,x.Rotation.Z,x.Rotation.W,x.Scale.X,x.Scale.Y,x.Scale.Z};
 static void ResamplePackage(string folder)
 {
  folder=Path.GetFullPath(folder);var path=Path.Combine(folder,"package.json");var pkg=JsonNode.Parse(File.ReadAllText(path))!;var records=new List<object>();
  if(pkg["assetType"]?.ToString()=="weapon")
  {
   var motions=new JsonObject();
   foreach(var f in Directory.GetFiles(Path.Combine(folder,"raw")).Where(f=>f.EndsWith(".anibnd",StringComparison.OrdinalIgnoreCase)||f.EndsWith(".anibnd.dcx",StringComparison.OrdinalIgnoreCase)))motions[Key(f)]=System.Text.Json.JsonSerializer.SerializeToNode(ReadPartMotion(File.ReadAllBytes(f)),JO);
   foreach(var clip in pkg["clips"]!.AsArray())
   {
    var parts=clip!["name"]!.ToString().Split('/');var tag=parts[0].ToLowerInvariant();var motion=motions[tag]??motions[tag.Replace("_m","").Replace("_l","")];
    var animation=motion?["animations"]!.AsArray().Single(a=>a!["name"]!.ToString()==parts[1])??throw new InvalidDataException("Missing weapon motion "+tag);
    string target=Path.Combine(folder,clip["file"]!.ToString());var before=Sha(target);using(var w=new BinaryWriter(File.Create(target)))foreach(var fr in animation["frames"]!.AsArray())foreach(var tr in fr!.AsArray())foreach(var v in tr!.AsArray())w.Write(v!.GetValue<float>());
    clip["sampling"]=SamplingVersion;records.Add(new{name=clip["name"]!.ToString(),before,after=Sha(target)});
   }
   File.WriteAllText(Path.Combine(folder,"weapon_motion.json"),motions.ToJsonString(JO));
  }
  else
  {
   var packs=new Dictionary<string,BND4>();byte[]? skeletonComp=null;
   foreach(var c in pkg["clips"]!.AsArray())
   {
    string pack=c!["pack"]!.ToString();if(packs.ContainsKey(pack))continue;var f=Path.Combine(folder,"source_native/chr",pack+".anibnd.dcx");
    if(!File.Exists(f))f=Path.Combine(pkg["root"]!.ToString(),"chr",pack+".anibnd.dcx");packs[pack]=BND4.Read(f);
   }
   skeletonComp=packs.Values.SelectMany(b=>b.Files).FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes;
   foreach(var c in pkg["clips"]!.AsArray())
   {
    var b=packs[c!["pack"]!.ToString()];var f=b.Files.Single(f=>Name(f.Name)==c["source"]!.ToString());var comp=b.Files.FirstOrDefault(f=>f.Name.EndsWith(".compendium"))?.Bytes??skeletonComp;
    var h=HKX.GenFakeFromTagFile(f.Bytes,comp);var data=new HavokAnimationData_SplineCompressed(0,Name(f.Name),h.DataSection.Objects.OfType<HKX.HKASplineCompressedAnimation>().Single());
    var binding=h.DataSection.Objects.OfType<HKX.HKAAnimationBinding>().Single();var map=Enumerable.Range(0,NativeData.Len(binding.TransformTrackToBoneIndices)).Select(i=>NativeData.AI(binding.TransformTrackToBoneIndices,i)).ToArray();
    if(data.FrameCount!=c["frames"]!.GetValue<int>()||!map.SequenceEqual(c["map"]!.AsArray().Select(v=>v!.GetValue<int>())))throw new InvalidDataException("Source clip dimensions changed");
    string target=Path.Combine(folder,c["file"]!.ToString());var before=Sha(target);float endpointDelta=0,nonterminalDelta=0,lastStep=0,endpointLeftLimitDelta=0;
    using(var w=new BinaryWriter(File.Create(target)))for(int fr=0;fr<data.FrameCount;fr++)for(int t=0;t<map.Length;t++)
    {
     var value=Values(SampleNonLooping(data,t,fr));var old=Values(data.GetTransformOnFrame(t,fr,false));
     for(int k=0;k<10;k++){float delta=Math.Abs(value[k]-old[k]);if(fr==data.FrameCount-1)endpointDelta=Math.Max(endpointDelta,delta);else nonterminalDelta=Math.Max(nonterminalDelta,delta);w.Write(value[k]);}
     if(fr==data.FrameCount-1&&fr>0){var near=Values(data.GetTransformOnFrame(t,MathF.BitDecrement((float)fr),false));for(int k=0;k<10;k++)endpointLeftLimitDelta=Math.Max(endpointLeftLimitDelta,Math.Abs(value[k]-near[k]));var previous=Values(SampleNonLooping(data,t,fr-1));for(int k=0;k<10;k++)lastStep=Math.Max(lastStep,Math.Abs(value[k]-previous[k]));}
    }
    c["sampling"]=SamplingVersion;records.Add(new{name=c["name"]!.ToString(),frames=data.FrameCount,blocks=data.BlockCount,span=data.NumFramesPerBlock-1,before,after=Sha(target),endpointDelta,nonterminalDelta,lastStep,endpointLeftLimitDelta});
   }
  }
  pkg["animationSampling"]=SamplingVersion;File.WriteAllText(path,pkg.ToJsonString(JO));
  // Equipment internal clips use the same spline decoder, including terminal knots.
  var equipment=Path.Combine(folder,"equipment");
  if(Directory.Exists(equipment))foreach(var sub in Directory.GetDirectories(equipment).Where(d=>File.Exists(Path.Combine(d,"package.json"))))
  {
   ResamplePackage(sub);var motions=JsonNode.Parse(File.ReadAllText(Path.Combine(sub,"weapon_motion.json")))!.AsObject();
   foreach(var entry in motions){var file=Directory.GetFiles(equipment,"*.motion.json").FirstOrDefault(f=>Path.GetFileName(f).Equals(entry.Key+".motion.json",StringComparison.OrdinalIgnoreCase));if(file!=null)File.WriteAllText(file,entry.Value!.ToJsonString(JO));}
  }
  Save(Path.Combine(folder,"sampling_report.json"),new{passed=true,version=SamplingVersion,clips=records});Log("RESAMPLE_DONE "+records.Count);
 }
}

