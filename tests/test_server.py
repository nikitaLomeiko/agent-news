import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import collect_articles, resolve_media_url, split_front_matter


class NewsTests(unittest.TestCase):
    def test_front_matter(self):
        metadata, body = split_front_matter("---\ntitle: Тест\ntags: [a, b]\n---\n# Текст")
        self.assertEqual(metadata["title"], "Тест")
        self.assertEqual(metadata["tags"], ["a", "b"])
        self.assertEqual(body, "# Текст")

    def test_collects_nested_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "section").mkdir()
            (root / "section" / "item.md").write_text("# Новость\n\nТекст", encoding="utf-8")
            articles = collect_articles({"news_dir": str(root)})
            self.assertEqual(len(articles), 1)
            self.assertEqual(articles[0]["title"], "Новость")
            self.assertEqual(articles[0]["file"], "section/item.md")

    def test_local_images_are_exposed_as_safe_media_urls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            article = root / "section" / "item.md"
            article.parent.mkdir()
            article.write_text(
                "---\nimage: ./images/cover one.jpg\n---\n![Внутри](./images/detail.png)",
                encoding="utf-8",
            )
            items = collect_articles({"news_dir": str(root)})
            self.assertEqual(items[0]["image"], "/media/section/images/cover%20one.jpg")
            self.assertIn("/media/section/images/detail.png", items[0]["content"])
            self.assertEqual(resolve_media_url("../../outside.png", article, root), "")

    def test_remote_image_url_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            article = root / "item.md"
            self.assertEqual(
                resolve_media_url("https://example.com/photo.jpg", article, root),
                "https://example.com/photo.jpg",
            )


if __name__ == "__main__":
    unittest.main()
