import os
import urllib.request
import json
import jwt
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

USER_POOL_ID = os.environ.get("USER_POOL_ID", "us-east-1_xxxxxxxxx")
REGION = USER_POOL_ID.split("_")[0]

JWKS_URL = f"https://cognito-idp.{REGION}.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json"

jwks = None

def get_jwks():
    global jwks
    if not jwks:
        with urllib.request.urlopen(JWKS_URL) as response:
            jwks = json.loads(response.read().decode())
    return jwks

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    try:
        # Get unverified header to extract key ID (kid)
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")

        keys = get_jwks().get("keys", [])
        key_data = next((k for k in keys if k["kid"] == kid), None)
        if not key_data:
            raise HTTPException(status_code=401, detail="Invalid token signature")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        
        # Verify token using PyJWT
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False} # App client ID sits in client_id not aud for Access Tokens
        )
        
        # We assume the user ID is in the 'sub' claim
        user_sub = payload.get("sub")
        if not user_sub:
            raise HTTPException(status_code=401, detail="Token missing subject claim")
            
        return payload
    except Exception as e:
        print(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
