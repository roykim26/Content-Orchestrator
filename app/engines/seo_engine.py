from urllib.parse import urlparse


class SEOEngine:
    def extract_rd_domain(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        return parsed.netloc
