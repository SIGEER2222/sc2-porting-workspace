"""打印 SC2 Status 枚举的完整定义。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import sc2api_pb2 as sc_pb

print("=== Status 枚举 ===")
for name, value in sc_pb.Status.items():
    print(f"  {value}: {name}")

print("\n=== ResponseCreateGame.Error 枚举 ===")
for name, value in sc_pb.ResponseCreateGame.Error.items():
    print(f"  {value}: {name}")

print("\n=== ResponseJoinGame.Error 枚举 ===")
if hasattr(sc_pb, "ResponseJoinGame"):
    for name, value in sc_pb.ResponseJoinGame.Error.items():
        print(f"  {value}: {name}")

print("\n=== PlayerType 枚举 ===")
for name, value in sc_pb.PlayerType.items():
    print(f"  {value}: {name}")

print("\n=== LocalMap 字段 ===")
for name, field in sc_pb.LocalMap.DESCRIPTOR.fields_by_name.items():
    print(f"  {name}: type={field.type}")

print("\n=== ResponseCreateGame 字段 ===")
for name, field in sc_pb.ResponseCreateGame.DESCRIPTOR.fields_by_name.items():
    print(f"  {name}: type={field.type}")

print("\n=== RequestCreateGame 字段 ===")
for name, field in sc_pb.RequestCreateGame.DESCRIPTOR.fields_by_name.items():
    print(f"  {name}: type={field.type}")
