import unittest
from unittest.mock import Mock

from fastapi import HTTPException

import server


class ConnectionPoolWarmupTest(unittest.TestCase):
    def test_warmup_raises_connection_error(self) -> None:
        pool = server.ConnectionPool(size=2)
        pool._new_connection = Mock(side_effect=RuntimeError("warehouse access denied"))

        with self.assertRaisesRegex(
            RuntimeError,
            "Pool warmup failed after 0/2: warehouse access denied",
        ):
            pool.warmup()


class ReadinessTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        server.pool_warmup_error = None
        server.pool_ready.clear()

    async def test_readiness_rejects_failed_warmup(self) -> None:
        server.pool_warmup_error = "warehouse access denied"

        with self.assertRaises(HTTPException) as raised:
            await server.ready()

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual(
            "Connection pool warmup failed; inspect API logs",
            raised.exception.detail,
        )

    async def test_readiness_accepts_successful_warmup(self) -> None:
        server.pool_ready.set()

        self.assertEqual({"status": "ready"}, await server.ready())


if __name__ == "__main__":
    unittest.main()
