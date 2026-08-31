"""Bounded, network-free robots.txt parsing and decisions (C2)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

ROBOTS_POLICY_VERSION = "official-site-robots-v1"
ROBOTS_MIME_TYPES = frozenset({"text/plain", "text/robots", "application/octet-stream"})


class RobotsPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RobotsParsePolicy:
    version: str = ROBOTS_POLICY_VERSION
    max_bytes: int = 512_000
    max_lines: int = 20_000
    max_rules: int = 10_000
    max_sitemaps: int = 32
    max_line_chars: int = 4_096

    def __post_init__(self) -> None:
        if self.version != ROBOTS_POLICY_VERSION:
            raise ValueError(f"unsupported robots policy version: {self.version}")
        if (
            min(
                self.max_bytes,
                self.max_lines,
                self.max_rules,
                self.max_sitemaps,
                self.max_line_chars,
            )
            < 1
        ):
            raise ValueError("robots ceilings must be positive")


DEFAULT_ROBOTS_PARSE_POLICY = RobotsParsePolicy()


@dataclass(frozen=True, slots=True)
class RobotsRule:
    allow: bool
    pattern: str


@dataclass(frozen=True, slots=True)
class RobotsGroup:
    user_agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    allowed: bool
    reason: str
    decision_ref: str


@dataclass(frozen=True, slots=True)
class RobotsDocument:
    robots_url: str
    policy_version: str
    groups: tuple[RobotsGroup, ...]
    sitemap_urls: tuple[str, ...]
    body_sha256: str
    default_allowed: bool
    status_reason: str

    def decide(self, *, user_agent: str, target_url: str) -> RobotsDecision:
        target = urlsplit(target_url)
        robots = urlsplit(self.robots_url)
        ref_payload = (
            f"{self.policy_version}\0{self.robots_url}\0{self.body_sha256}\0"
            f"{user_agent.casefold()}\0{target_url}"
        )
        decision_ref = f"robots:{hashlib.sha256(ref_payload.encode()).hexdigest()}"
        if target.scheme.lower() not in {"http", "https"} or target.hostname is None:
            return RobotsDecision(False, "invalid_target_url", decision_ref)
        if target.hostname.lower().rstrip(".") != (robots.hostname or "").lower().rstrip("."):
            return RobotsDecision(False, "robots_host_mismatch", decision_ref)
        if not self.groups:
            return RobotsDecision(self.default_allowed, self.status_reason, decision_ref)

        token = user_agent.casefold()
        matching: list[tuple[int, RobotsGroup]] = []
        for group in self.groups:
            specificity = max(
                (
                    0 if agent == "*" else len(agent)
                    for agent in group.user_agents
                    if agent == "*" or agent in token
                ),
                default=-1,
            )
            if specificity >= 0:
                matching.append((specificity, group))
        if not matching:
            return RobotsDecision(True, "no_matching_user_agent_group", decision_ref)
        highest = max(item[0] for item in matching)
        rules = tuple(rule for score, group in matching if score == highest for rule in group.rules)
        path = target.path or "/"
        if target.query:
            path = f"{path}?{target.query}"
        winners: list[RobotsRule] = []
        winning_length = -1
        for rule in rules:
            if not rule.pattern:
                continue
            expression = re.escape(rule.pattern).replace(r"\*", ".*")
            expression = f"{expression[:-2]}$" if expression.endswith(r"\$") else f"{expression}.*"
            if re.match(expression, path):
                length = len(rule.pattern.replace("*", "").rstrip("$"))
                if length > winning_length:
                    winners = [rule]
                    winning_length = length
                elif length == winning_length:
                    winners.append(rule)
        if not winners:
            return RobotsDecision(True, "no_matching_rule", decision_ref)
        allowed = any(rule.allow for rule in winners)
        return RobotsDecision(allowed, "allow_rule" if allowed else "disallow_rule", decision_ref)


def _empty_document(
    robots_url: str,
    *,
    policy: RobotsParsePolicy,
    body: bytes,
    default_allowed: bool,
    reason: str,
) -> RobotsDocument:
    return RobotsDocument(
        robots_url=robots_url,
        policy_version=policy.version,
        groups=(),
        sitemap_urls=(),
        body_sha256=hashlib.sha256(body).hexdigest(),
        default_allowed=default_allowed,
        status_reason=reason,
    )


def parse_robots(
    body: bytes,
    *,
    robots_url: str,
    media_type: str | None,
    http_status: int = 200,
    policy: RobotsParsePolicy = DEFAULT_ROBOTS_PARSE_POLICY,
) -> RobotsDocument:
    """Parse a bounded robots response without fetching sitemap declarations."""

    if len(body) > policy.max_bytes:
        raise RobotsPolicyError("robots_size_ceiling_exceeded")
    if http_status in {401, 403}:
        return _empty_document(
            robots_url,
            policy=policy,
            body=body,
            default_allowed=False,
            reason="robots_http_refused",
        )
    if http_status == 404:
        return _empty_document(
            robots_url,
            policy=policy,
            body=body,
            default_allowed=True,
            reason="robots_not_found",
        )
    if http_status < 200 or http_status >= 300:
        return _empty_document(
            robots_url,
            policy=policy,
            body=body,
            default_allowed=False,
            reason="robots_unavailable_fail_closed",
        )
    normalized_mime = (media_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in ROBOTS_MIME_TYPES:
        raise RobotsPolicyError("unsupported_robots_media_type")
    text = body.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > policy.max_lines:
        raise RobotsPolicyError("robots_line_ceiling_exceeded")

    groups: list[RobotsGroup] = []
    agents: list[str] = []
    rules: list[RobotsRule] = []
    sitemaps: list[str] = []
    total_rules = 0

    def finish_group() -> None:
        nonlocal agents, rules
        if agents:
            groups.append(RobotsGroup(tuple(dict.fromkeys(agents)), tuple(rules)))
        agents = []
        rules = []

    for raw_line in lines:
        if len(raw_line) > policy.max_line_chars:
            raise RobotsPolicyError("robots_line_size_ceiling_exceeded")
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.casefold()
        if field == "user-agent":
            if rules:
                finish_group()
            if value:
                agents.append(value.casefold())
        elif field in {"allow", "disallow"} and agents:
            total_rules += 1
            if total_rules > policy.max_rules:
                raise RobotsPolicyError("robots_rule_ceiling_exceeded")
            rules.append(RobotsRule(field == "allow", value))
        elif field == "sitemap" and value:
            if len(sitemaps) >= policy.max_sitemaps:
                raise RobotsPolicyError("robots_sitemap_ceiling_exceeded")
            sitemaps.append(urljoin(robots_url, value))
    finish_group()
    return RobotsDocument(
        robots_url=robots_url,
        policy_version=policy.version,
        groups=tuple(groups),
        sitemap_urls=tuple(sitemaps),
        body_sha256=hashlib.sha256(body).hexdigest(),
        default_allowed=True,
        status_reason="robots_rules_parsed",
    )


__all__ = [
    "ROBOTS_MIME_TYPES",
    "ROBOTS_POLICY_VERSION",
    "DEFAULT_ROBOTS_PARSE_POLICY",
    "RobotsDecision",
    "RobotsDocument",
    "RobotsGroup",
    "RobotsParsePolicy",
    "RobotsPolicyError",
    "RobotsRule",
    "parse_robots",
]
