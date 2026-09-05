"""Robust eQSL OutBox downloader for QSO Manager 5.1.

The eQSL DownloadADIF endpoint normally returns an HTML build/result page with
links to a generated .ADI/.TXT file. Older code tried to parse that HTML page
as ADIF first, which can produce a bogus one-record snapshot when HTML/input
markup happens to look like ADIF tags. This adapter treats HTML as a control
page, follows the generated download link, and validates the resulting record
count when eQSL reports one.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .cloud_logs import ADIFParser, CloudProviderError, EQSLCloudAdapter


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(str(value))


class EQSLCloudAdapterV510(EQSLCloudAdapter):
    """Download the complete eQSL OutBox from the generated ADIF file."""

    USER_AGENT = "PU2BRU-QSO-Manager/5.1 (PU2BRU)"

    @staticmethod
    def _looks_html(response, body: str) -> bool:
        content_type = str(response.headers.get("content-type") or "").lower()
        sample = body[:2000].lower()
        return "text/html" in content_type or "<html" in sample or "<body" in sample or "<!doctype" in sample

    @staticmethod
    def _reported_count(body: str) -> Optional[int]:
        clean = re.sub(r"<[^>]+>", " ", html.unescape(body))
        clean = re.sub(r"\s+", " ", clean)
        patterns = (
            r"there\s+were\s+([0-9][0-9.,]*)\s+records?",
            r"([0-9][0-9.,]*)\s+records?\s+(?:were\s+)?(?:built|generated|found)",
        )
        for pattern in patterns:
            match = re.search(pattern, clean, flags=re.I)
            if not match:
                continue
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                return int(digits)
        return None

    @staticmethod
    def _download_links(body: str, base_url: str) -> List[str]:
        parser = _HrefParser()
        try:
            parser.feed(body)
        except Exception:
            pass
        parser.hrefs.extend(re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", body, flags=re.I))

        ranked: List[Tuple[int, str]] = []
        seen = set()
        for href in parser.hrefs:
            absolute = urljoin(base_url, html.unescape(href).strip())
            if absolute in seen:
                continue
            seen.add(absolute)
            path = urlparse(absolute).path.lower()
            if path.endswith((".adi", ".adif")):
                ranked.append((0, absolute))
            elif path.endswith(".txt") and ("download" in path or "downloadedfiles" in path):
                ranked.append((1, absolute))
        ranked.sort(key=lambda item: item[0])
        return [url for _, url in ranked]

    @staticmethod
    def _parse_adif(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        return ADIFParser().parse(html.unescape(text))

    @staticmethod
    def _validate_count(records: List[Dict[str, Any]], expected: Optional[int]) -> None:
        if expected is not None and len(records) != expected:
            raise CloudProviderError(
                f"Download eQSL incompleto: a página informa {expected} QSOs, "
                f"mas o arquivo ADIF contém {len(records)}. O snapshot anterior foi preservado."
            )

    def fetch_all(self) -> Dict[str, Any]:
        params = self._params()
        response = self.client.get(
            urljoin(self.base_url, "DownloadADIF.cfm"),
            params=params,
            headers={"User-Agent": self.USER_AGENT},
        )
        response.raise_for_status()
        body = html.unescape(response.text)
        expected = self._reported_count(body)

        if self._looks_html(response, body):
            clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
            lowered = clean.lower()
            if "not yet logged in" in lowered or ("invalid" in lowered and "password" in lowered):
                raise CloudProviderError("eQSL recusou as credenciais para download do OutBox")

            links = self._download_links(body, str(response.url))
            diagnostics: List[str] = []
            for link in links:
                downloaded = self.client.get(link, headers={"User-Agent": self.USER_AGENT})
                if not downloaded.is_success:
                    diagnostics.append(f"{urlparse(link).path}: HTTP {downloaded.status_code}")
                    continue
                records, errors = self._parse_adif(downloaded.text)
                if not records:
                    diagnostics.append(f"{urlparse(link).path}: 0 QSOs")
                    continue
                self._validate_count(records, expected)
                return {
                    "records": records,
                    "metadata": {
                        "coverage": "API_FULL_SYNC",
                        "normalized_export": True,
                        "parse_errors": errors[:10],
                        "download_strategy": "OUTBOX_ADIF_FILE",
                        "remote_reported_count": expected,
                        "download_file": urlparse(link).path.rsplit("/", 1)[-1],
                    },
                }

            if expected == 0:
                return {
                    "records": [],
                    "metadata": {
                        "coverage": "API_FULL_SYNC",
                        "normalized_export": True,
                        "download_strategy": "OUTBOX_ADIF_FILE",
                        "remote_reported_count": 0,
                    },
                }

            detail = " | ".join(diagnostics[:4])
            raise CloudProviderError(
                "eQSL criou a página de download do OutBox, mas o QSO Manager não conseguiu obter o arquivo ADIF"
                + (f". Diagnóstico: {detail}" if detail else ".")
            )

        records, errors = self._parse_adif(body)
        if not records and expected != 0:
            raise CloudProviderError("eQSL OutBox download did not return an ADIF log")
        self._validate_count(records, expected)
        return {
            "records": records,
            "metadata": {
                "coverage": "API_FULL_SYNC",
                "normalized_export": True,
                "parse_errors": errors[:10],
                "download_strategy": "DIRECT_ADIF",
                "remote_reported_count": expected,
            },
        }
