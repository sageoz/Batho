import requests
import time
from datetime import datetime
from cvss import CVSS3

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"


class OSVScanner:
    def __init__(self, rate_limit=0.1):
        self.rate_limit = rate_limit
        self.cache = {}

    # ------------------ PUBLIC ------------------

    def scan(self, packages: list[dict]) -> list[dict]:
        raw_results = self._scan_packages(packages)
        return self._transform_to_batho_schema(raw_results)

    # ------------------ CORE ------------------

    def _build_queries(self, packages):
        return [
            {
                "package": {
                    "name": pkg["name"],
                    "ecosystem": pkg["ecosystem"]
                },
                "version": pkg["version"]
            }
            for pkg in packages
        ]

    def _scan_packages(self, packages):
        queries = self._build_queries(packages)

        try:
            response = requests.post(
                OSV_BATCH_URL,
                json={"queries": queries},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            print(f"[ERROR] OSV batch request failed: {e}")
            return []

        results = data.get("results", [])
        output = []

        for pkg, result in zip(packages, results):
            vulns = result.get("vulns", [])
            detailed_vulns = []

            for v in vulns:
                vid = v["id"]

                details = self._fetch_vuln_details(vid)

                score_data = self._extract_cvss(details)
                severity_data = self._get_cvss_severity(score_data)

                detailed_vulns.append({
                    "id": vid,
                    "summary": details.get("summary"),
                    "severity": severity_data["severity"],
                    "cvss_score": (
                        float(severity_data["score"])
                        if severity_data["score"] is not None else None
                    )
                })

            output.append({
                "package": pkg["name"],
                "version": pkg["version"],
                "ecosystem": pkg["ecosystem"],
                "vulnerable": len(detailed_vulns) > 0,
                "vulnerability_count": len(detailed_vulns),
                "vulnerabilities": detailed_vulns
            })

        return output

    # ------------------ FETCH ------------------

    def _fetch_vuln_details(self, vuln_id):
        if vuln_id in self.cache:
            return self.cache[vuln_id]

        try:
            res = requests.get(OSV_VULN_URL + vuln_id, timeout=10)
            res.raise_for_status()
            data = res.json()
            self.cache[vuln_id] = data
            time.sleep(self.rate_limit)
            return data
        except requests.RequestException:
            return {"id": vuln_id}

    # ------------------ CVSS ------------------

    def _extract_cvss(self, details):
        severity = details.get("severity", [])
        for s in severity:
            if s.get("type") == "CVSS_V3":
                return s.get("score")
        return None

    def _get_cvss_severity(self, score_data):
        if not score_data:
            return {"score": None, "severity": "UNKNOWN"}

        try:
            score = float(score_data)
        except ValueError:
            try:
                c = CVSS3(score_data)
                score = c.base_score
            except Exception:
                return {"score": None, "severity": "UNKNOWN"}

        if score == 0:
            severity = "NONE"
        elif score <= 3.9:
            severity = "LOW"
        elif score <= 6.9:
            severity = "MEDIUM"
        elif score <= 8.9:
            severity = "HIGH"
        else:
            severity = "CRITICAL"

        return {"score": score, "severity": severity}

    # ------------------ BATHO SCHEMA ------------------

    def _transform_to_batho_schema(self, scan_results):
        output = []
        severity_order = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

        for result in scan_results:
            vulns = result["vulnerabilities"]

            max_severity = "NONE"
            for v in vulns:
                if v["severity"] in severity_order:
                    if severity_order.index(v["severity"]) > severity_order.index(max_severity):
                        max_severity = v["severity"]

            output.append({
                "type": "dependency_vulnerability",
                "id": f"{result['package']}@{result['version']}",

                "package": {
                    "name": result["package"],
                    "version": result["version"],
                    "ecosystem": result["ecosystem"]
                },

                "risk": {
                    "has_vulnerabilities": result["vulnerable"],
                    "count": result["vulnerability_count"],
                    "max_severity": max_severity
                },

                "vulnerabilities": [
                    {
                        "id": v["id"],
                        "summary": v["summary"],
                        "severity": {
                            "level": v["severity"],
                            "score": v["cvss_score"]
                        }
                    }
                    for v in vulns
                ],

                "metadata": {
                    "source": "osv.dev",
                    "scanned_at": datetime.utcnow().isoformat()
                }
            })

        return output