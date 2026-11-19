using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Numerics;
using SoulsFormats;
using SoulsAssetPipeline.Animation;
using TAE=SoulsFormats.TAE;
static class NativeData {
 static JsonSerializerOptions JO=new(){WriteIndented=false,IncludeFields=true};
 static BindingFlags BF=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance;
 static float[] V(Vector3 v)=>new[]{v.X,v.Y,v.Z};
 static float[] V4(Vector4 v)=>new[]{v.X,v.Y,v.Z,v.W};
 static float[] Mat(Matrix4x4 m)=>new[]{m.M11,m.M12,m.M13,m.M14,m.M21,m.M22,m.M23,m.M24,m.M31,m.M32,m.M33,m.M34,m.M41,m.M42,m.M43,m.M44};
 public static object Field(object o,string n)=>o.GetType().GetField(n,BF)?.GetValue(o)??o.GetType().GetProperty(n,BF)?.GetValue(o);
 static Dictionary<string,object> Props(object o) {var d=new Dictionary<string,object>{{"type",o.GetType().Name}}; foreach(var f in o.GetType().GetFields(BindingFlags.Public|BindingFlags.Instance)) d[f.Name]=f.GetValue(o);foreach(var p in o.GetType().GetProperties(BindingFlags.Public|BindingFlags.Instance)) if(p.GetIndexParameters().Length==0) try{d[p.Name]=p.GetValue(o);}catch{} return d;}
 static void Save(string p,object o){File.WriteAllText(p,JsonSerializer.Serialize(o,JO),new UTF8Encoding(false));Console.WriteLine("WROTE "+p);}
 public static object TaeData(TAE t,string name)=> new{name,id=t.ID,animations=t.Animations.Select(a=>new{id=a.ID,name=a.AnimFileName,header=Props(a.MiniHeader),events=a.Events.Select(e=>new{type=e.Type,start=e.StartTime,end=e.EndTime,raw=Convert.ToHexString(e.GetParameterBytes(t.BigEndian))})})};
 static float[] DummyFrame(FLVER.Dummy d){var v=new Microsoft.Xna.Framework.Vector3(d.Forward.X,d.Forward.Y,d.Forward.Z);var u=d.UseUpwardVector?new Microsoft.Xna.Framework.Vector3(d.Upward.X,d.Upward.Y,d.Upward.Z):Microsoft.Xna.Framework.Vector3.Up;var m=Microsoft.Xna.Framework.Matrix.CreateRotationY(MathF.PI)*Microsoft.Xna.Framework.Matrix.CreateWorld(Microsoft.Xna.Framework.Vector3.Zero,Microsoft.Xna.Framework.Vector3.Normalize(v),Microsoft.Xna.Framework.Vector3.Normalize(u))*Microsoft.Xna.Framework.Matrix.CreateTranslation(d.Position.X,d.Position.Y,d.Position.Z);return new[]{m.M11,m.M12,m.M13,m.M14,m.M21,m.M22,m.M23,m.M24,m.M31,m.M32,m.M33,m.M34,m.M41,m.M42,m.M43,m.M44};}
 public static void Flver(string path,string dst){var f=FLVER2.Read(path);var world=new Matrix4x4[f.Nodes.Count];var done=new bool[f.Nodes.Count];Matrix4x4 FK(int i){if(done[i])return world[i];var n=f.Nodes[i];world[i]=n.ComputeLocalTransform()*(n.ParentIndex>=0?FK(n.ParentIndex):Matrix4x4.Identity);done[i]=true;return world[i];}
 var nodes=f.Nodes.Select((n,i)=>new{name=n.Name,parent=n.ParentIndex,local=Mat(n.ComputeLocalTransform()),world=Mat(FK(i))}).ToArray();
 var sk=f.Skeletons?.BaseSkeleton?.Select(n=>new{node=n.NodeIndex,parent=n.ParentIndex}).ToArray();
 Save(dst,new{source=path,version=f.Header.Version,nodes,skeleton=sk,dummies=f.Dummies.Select(d=>new{id=d.ReferenceID,frame=DummyFrame(d),pos=V(d.Position),forward=V(d.Forward),up=V(d.Upward),parent=d.ParentBoneIndex,attach=d.AttachBoneIndex,follow=d.Flag1,useUp=d.UseUpwardVector}),materials=f.Materials.Select(m=>new{name=m.Name,mtd=m.MTD,textures=m.Textures.Select(t=>new{type=t.ParamName,path=t.Path})}),meshes=f.Meshes.Select(m=>{var fs=m.FaceSets.Where(s=>s.Flags==FLVER2.FaceSet.FSFlags.None).ToArray();if(fs.Length==0)fs=m.FaceSets.Take(1).ToArray();return new{material=m.MaterialIndex,usesBoneIndices=m.VertexBuffers.Any(vb=>f.BufferLayouts[vb.LayoutIndex].Any(l=>l.Semantic==FLVER.LayoutSemantic.BoneIndices)),info=PropsForMesh(m),pos=m.Vertices.Select(v=>V(v.Position)),normal=m.Vertices.Select(v=>V(v.Normal)),uv=m.Vertices.Select(v=>v.UVs.Select(V)),colors=m.Vertices.Select(v=>v.Colors.Select(c=>new[]{c.R,c.G,c.B,c.A})),tangent=m.Vertices.Select(v=>v.Tangents.Select(V4)),indices=fs.SelectMany(s=>s.Triangulate(false,false)).ToArray(),boneIndices=m.Vertices.Select(v=>Enumerable.Range(0,4).Select(i=>v.BoneIndices[i]).ToArray()),weights=m.Vertices.Select(v=>Enumerable.Range(0,4).Select(i=>v.BoneWeights[i]).ToArray()),normalW=m.Vertices.Select(v=>v.NormalW).ToArray()};})});
 }
 static object PropsForMesh(FLVER2.Mesh m){var d=new Dictionary<string,object>();foreach(var p in m.GetType().GetProperties())if(p.Name is "Dynamic" or "UseBoneWeights" or "DefaultBoneIndex" or "NodeIndex" or "BoneIndices")d[p.Name]=p.GetValue(m);return d;}
 public static int Len(object arr)=>Convert.ToInt32(Field(arr,"Size"));
 public static object Item(object arr,int i){var data=Field(arr,"Elements");if(data is System.Collections.IList l)return l[i];data=Field(arr,"Data");if(data is System.Collections.IList ll)return ll[i];var ix=arr.GetType().GetProperty("Item");if(ix!=null)return ix.GetValue(arr,new object[]{i});throw new Exception("array "+arr.GetType());}
 public static int AI(object a,int i){var x=Item(a,i);return Convert.ToInt32(Field(x,"data")??Field(x,"Data")??Field(x,"Value")??x);}
 public static string Str(object o){if(o==null)return "";if(o is string s)return s;var m=o.GetType().GetMethod("GetString",Type.EmptyTypes);return m!=null?m.Invoke(o,null)?.ToString():(Field(o,"Data")??o).ToString();}
 static HKX ReadHkx(byte[] data,byte[] comp){return HKX.GenFakeFromTagFile(data,comp);}

}
