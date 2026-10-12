"""切块必须保留长页末尾，并且不能额外产生完全重复的尾块。"""

from copy import deepcopy
import unittest

from supportpilot.knowledge.retrieval import chunk_pages, retrieve_passages


class RetrievalTests(unittest.TestCase):
    def test_long_page_preserves_every_character(self):
        text = "".join(chr(0x4E00 + i) for i in range(2700))
        pages = [{"page": 1, "text": text}]
        original = deepcopy(pages)
        chunks = chunk_pages(pages, {"document_id": "doc", "source_revision": "rev"})
        restored = chunks[0]["text"] + "".join(c["text"][200:] for c in chunks[1:])
        self.assertEqual(restored, text)
        self.assertEqual(pages, original)

    def test_one_chunk_page_has_no_duplicate_tail(self):
        chunks = chunk_pages([{"page": 1, "text": "x" * 1100}],
                            {"document_id": "doc", "source_revision": "rev"})
        self.assertEqual(len(chunks), 1)

    def test_empty_collection_does_not_embed(self):
        class EmptyCollection:
            def count(self):
                return 0

        def unexpected_embedding(texts):
            self.fail("空集合不应请求嵌入")

        self.assertEqual(retrieve_passages(EmptyCollection(), unexpected_embedding, "问题", "p"), [])


if __name__ == "__main__":
    unittest.main()
