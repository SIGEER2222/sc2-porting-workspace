"""知识库索引配置与 manifest 的一致性测试。"""
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestKnowledgeIndexManifest(unittest.TestCase):
    def test_configured_embedding_model_matches_manifest(self):
        """已建立索引必须对应当前配置的 embedding 模型和维度。"""
        config_path = REPO_ROOT / "tools" / "kb" / "kb-config.json"
        manifest_path = REPO_ROOT / "artifacts" / "kb-index" / "manifest.json"

        config = json.loads(config_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["model_name"], config["embeddingModel"])
        self.assertEqual(manifest["model_dim"], config["embeddingDim"])


if __name__ == "__main__":
    unittest.main()
