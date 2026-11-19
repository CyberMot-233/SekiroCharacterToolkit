using System.Text.RegularExpressions;
using SoulsFormats;

partial class Program
{
 static void ListAnimations(string root,string id,string anim,string output)
 {
  var rows=new List<object>();
  foreach(var path in Packs(root,anim,".anibnd.dcx"))
  {
   string pack=Name(path).Replace(".anibnd.dcx","");
   foreach(var file in BND4.Read(path).Files)
   {
    string name=Name(file.Name);
    if(!Regex.IsMatch(name,@"^a[0-9]+_[0-9]+[.]hkx$",RegexOptions.IgnoreCase))continue;
    rows.Add(new{name=pack+"/"+Key(name),id=Key(name),pack,bytes=file.Bytes.Length,
     auxiliary=id=="c0000"&&Regex.IsMatch(name,@"^a000_790[0-9]{3}[.]hkx$",RegexOptions.IgnoreCase)});
   }
  }
  Save(output,new{character=id,animationSource=anim,count=rows.Count,actions=rows,
   note="原始 HKX ID，不猜测动作中文名称；脸部辅助源会随选中动作保留。"});
  Log($"ACTIONS {rows.Count} -> {output}");
 }
}
