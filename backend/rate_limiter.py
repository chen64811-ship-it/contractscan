"""
Rate limiter utility
Per-IP rate limiting using in-memory tracking.
"""
import time
from collections import defaultdict
from fastapi import Request, HTTPException


class RateLimiter:
    """Simple in-memory rate limiter with sliding window."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        return request.client.host if request.client else "unknown"

    def _cleanup(self, ip: str):
        now = time.time()
        self._requests[ip] = [
            t for t in self._requests[ip]
            if now - t < self.window_seconds
        ]

    def check(self, request: Request) -> bool:
        ip = self._get_ip(request)
        self._cleanup(ip)
        if len(self._requests[ip]) >= self.max_requests:
            raise HTTPException(
                429,
                f"Rate limit exceeded. Max {self.max_requests} requests per {self.window_seconds}s. Please wait."
            )
        self._requests[ip].append(time.time())
        return True


# Global instance: 5 requests per minute for analyze endpoints
analyze_limiter = RateLimiter(max_requests=5, window_seconds=60)

# Debug endpoint: 10 requests per minute
debug_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Unlock endpoint: 3 attempts per minute (anti-brute-force)
unlock_limiter = RateLimiter(max_requests=3, window_seconds=60)
