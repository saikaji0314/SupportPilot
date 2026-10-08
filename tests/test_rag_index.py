"""验证部分入库失败后的续跑，以及重复运行不会重复请求嵌入。"""

import contextlib
import io
import unittest

from supportpilot.rag_support import index_chunks


class MemoryCollection:
    def __init__(self):
        self.ids = set()

    def get(self, ids, include):
        return {"ids": [item for item in ids if item in self.ids]}

    def upsert(self, ids, **kwargs):
        self.ids.update(ids)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [{"id": str(i), "text": f"chunk {i}", "metadata": {"page": i}}
                       for i in range(23)]
        self.collection = MemoryCollection()

    def test_resume_after_embedding_failure_and_repeat(self):
        calls = []

        def failing_embedder(texts):
            calls.append(texts)
            if len(calls) == 2:
                raise TimeoutError("private service response")
            return [[1.0, 0.0] for _ in texts]

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "请求嵌入失败") as error:
                index_chunks(self.collection, failing_embedder, self.chunks)
        self.assertNotIn("private service response", str(error.exception))
        self.assertEqual(len(self.collection.ids), 10)
        resumed = []

        def embedder(texts):
            resumed.extend(texts)
            return [[1.0, 0.0] for _ in texts]

        with contextlib.redirect_stdout(io.StringIO()):
            index_chunks(self.collection, embedder, self.chunks)
            index_chunks(self.collection, embedder, self.chunks)
        self.assertEqual(resumed, [item["text"] for item in self.chunks[10:]])
        self.assertEqual(len(self.collection.ids), 23)

    def test_write_failure_identifies_stage(self):
        def fail_write(**kwargs):
            raise OSError("private database detail")

        self.collection.upsert = fail_write
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "写入 Chroma失败"):
                index_chunks(self.collection, lambda texts: [[1.0] for _ in texts], self.chunks)
        self.assertEqual(len(self.collection.ids), 0)


if __name__ == "__main__":
    unittest.main()
