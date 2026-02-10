import aioboto3
from app.utils.config import settings

class R2Handler:
    def __init__(self):
        # 환경변수 로드
        self.endpoint_url = settings.cloudflare_endpoint_url
        self.access_key = settings.cloudflare_access_key
        self.secret_key = settings.cloudflare_secret_key
        self.bucket_name = settings.cloudflare_bucket_name
        self._session = None

    async def initialize(self):
        """
        aioboto3 세션을 초기화합니다.
        FastAPI lifespan에서 호출하는 것을 권장합니다.
        """
        if self._session is None:
            self._session = aioboto3.Session()

    async def close(self):
        """
        세션을 종료합니다. 인터페이스 일관성을 위해 유지합니다.
        """
        self._session = None

    async def upload_file(self, file_content: bytes, object_name: str, content_type: str = None) -> str:
        """
        Cloudflare R2 버킷에 파일을 업로드합니다.
        
        :param file_content: 업로드할 파일의 바이트 데이터
        :param object_name: 저장될 파일 명 (경로 포함 가능)
        :param content_type: MIME 타입 (예: image/png)
        :return: 저장된 객체의 키(이름)
        """
        if self._session is None:
            await self.initialize()

        async with self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            # Cloudflare R2는 region_name이 "auto" 혹은 비어있어도 되지만 
            # 일반적인 S3 호환 라이브러리들은 region을 요구할 수 있습니다.
            region_name="auto" 
        ) as s3:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            await s3.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_content,
                **extra_args
            )
            
            return object_name

    async def delete_file(self, object_name: str):
        """
        R2 버킷에서 파일을 삭제합니다.
        """
        if self._session is None:
            await self.initialize()

        async with self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="auto"
        ) as s3:
            await s3.delete_object(Bucket=self.bucket_name, Key=object_name)

    async def get_download_url(self, object_name: str, expires_in: int = 3600) -> str:
        """
        파일에 접근할 수 있는 Pre-signed URL을 생성합니다.
        만약 버킷이 Public이라면 직접 URL을 구성할 수도 있습니다.
        """
        if self._session is None:
            await self.initialize()

        async with self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="auto"
        ) as s3:
            url = await s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expires_in
            )
            return url

    def get_object_name_from_url(self, url: str) -> str:
        """
        전체 R2 공개 URL에서 object_name(key)을 추출합니다.
        settings.cloudflare_public_url 설정을 기준으로 파일 경로를 분리합니다.
        """
        if not url:
            return None
            
        base_url = settings.cloudflare_public_url.rstrip("/")
        # 프로토콜 제거 (비교를 위해)
        clean_url = url.replace("https://", "").replace("http://", "")
        clean_base = base_url.replace("https://", "").replace("http://", "")
        
        if clean_base in clean_url:
            # base_url 이후의 경로를 반환
            object_name = clean_url.split(clean_base)[-1].lstrip("/")
            return object_name
            
        return None

# 전역 핸들러 인스턴스
r2_handler = R2Handler()

def get_r2_handler():
    return r2_handler
