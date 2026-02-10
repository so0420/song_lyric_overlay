import secrets
import hashlib
from typing import Optional
from dataclasses import dataclass
from app.utils.config import settings
from app.database.redis.redis import redis, RedisHandler
from app.utils.log import logger

@dataclass
class OTPVerificationResult:
    success: bool
    message: str
    remaining_attempts: Optional[int] = None

class OTP:
    # Constants for keys and messages
    PREFIX = "otp:"
    FIELD_CODE = "code"
    FIELD_ATTEMPTS = "attempts"
    
    MSG_EXPIRED = "OTP가 만료되었거나 존재하지 않습니다."
    MSG_ERROR = "데이터 오류가 발생했습니다."
    MSG_LIMIT_EXCEEDED = "최대 인증 시도 횟수를 초과했습니다. 다시 요청해주세요."
    MSG_SUCCESS = "인증에 성공했습니다."
    MSG_MISMATCH = "인증 코드가 일치하지 않습니다."

    def __init__(self, redis_handler: RedisHandler = None, ttl: int = None, max_attempts: int = None):
        self._redis = redis_handler if redis_handler is not None else redis
        self.ttl = ttl if ttl is not None else settings.otp_ttl
        self.max_attempts = max_attempts if max_attempts is not None else settings.otp_max_attempts

    def generate_otp_code(self, length: int = 6) -> str:
        """
        Generates a numeric OTP of the specified length.
        """
        return f"{secrets.randbelow(10 ** length):0{length}d}"

    def _hash_code(self, code: str) -> str:
        """
        Returns SHA-256 hash of the code.
        """
        return hashlib.sha256(code.encode()).hexdigest()

    async def create_otp(self, key: str, length: int = 6) -> str:
        """
        Generates an OTP and stores its hash in Redis using a Hash structure.
        Overwrites if it already exists.
        """
        code = self.generate_otp_code(length)
        hashed_code = self._hash_code(code)
        redis_key = f"{self.PREFIX}{key}"
        
        # Use Redis Hash for atomic field management
        data = {
            self.FIELD_CODE: hashed_code,
            self.FIELD_ATTEMPTS: 0
        }
        
        try:
            # Pipeline could be used here for strict atomicity, but HSET + EXPIRE is generally acceptable
            # as the window for error is extremely small and non-critical (orphan key possibility).
            async with self._redis.client.pipeline() as pipe:
                await pipe.delete(redis_key) # Ensure clean slate
                # Use loop for hset to ensure compatibility if variadic HSET is issues
                for k, v in data.items():
                    await pipe.hset(redis_key, k, v)
                await pipe.expire(redis_key, self.ttl)
                await pipe.execute()
                
            logger.info(f"OTP created for {key}. TTL: {self.ttl}")
            return code
        except Exception as e:
            logger.error(f"Failed to create OTP for {key}: {e}")
            raise

    async def verify_otp(self, key: str, input_code: str) -> OTPVerificationResult:
        """
        Verifies the OTP by comparing hashes.
        Uses HINCRBY for atomic attempt counting without resetting TTL.
        """
        redis_key = f"{self.PREFIX}{key}"
        
        # Check existence and fetch code
        # We only need the code to compare. Attempts will be handled atomically if needed.
        stored_hash = await self._redis.client.hget(redis_key, self.FIELD_CODE)
        
        if not stored_hash:
            logger.warning(f"OTP lookup failed for {key}: Key not found or expired")
            return OTPVerificationResult(False, self.MSG_EXPIRED)

        # 1. Verify Code Match (Hash comparison)
        input_hash = self._hash_code(input_code)
        
        if stored_hash == input_hash:
            # Success: Delete and return
            await self._redis.delete(redis_key)
            logger.info(f"OTP verified successfully for {key}")
            return OTPVerificationResult(True, self.MSG_SUCCESS)
        
        # 2. Handle Mismatch (Atomic Increment)
        # HINCRBY increments and returns the new value
        attempts = await self._redis.client.hincrby(redis_key, self.FIELD_ATTEMPTS, 1)
        
        if attempts >= self.max_attempts:
            await self._redis.delete(redis_key)
            logger.warning(f"OTP max attempts reached for {key}")
            return OTPVerificationResult(False, self.MSG_LIMIT_EXCEEDED, 0)
            
        remaining = self.max_attempts - attempts
        logger.info(f"OTP mismatch for {key}. Attempts: {attempts}, Remaining: {remaining}")
        return OTPVerificationResult(
            False, 
            f"{self.MSG_MISMATCH} (남은 횟수: {remaining}회)",
            remaining
        )

otp_manager = OTP()

__all__ = ["otp_manager", "OTP", "OTPVerificationResult"]

if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("--- OTP Test Start ---")
        try:
            await redis.initialize()
            m = otp_manager
            
            # 1. Create
            email = "test@example.com"
            code = await m.create_otp(email)
            print(f"1. Created OTP for {email}: {code}")
            
            # 2. Verify Wrong Code
            res = await m.verify_otp(email, "000000")
            print(f"2. Verify Wrong Result: {res}")
            
            # 3. Verify Correct Code
            res = await m.verify_otp(email, code)
            print(f"3. Verify Correct Result: {res}")
            
            # 4. Verify Again (Should fail/expire)
            res = await m.verify_otp(email, code)
            print(f"4. Verify Duplicate Result: {res}")
            
        except Exception as e:
            print(f"Test Error: {e}")
        finally:
            await redis.close()
            print("--- OTP Test End ---")

    asyncio.run(test())
