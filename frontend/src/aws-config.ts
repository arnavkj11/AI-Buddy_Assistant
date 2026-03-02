// Temporary placeholder for config injected after CDK deployment
// In a real flow, a script injects the actual values here
export const awsConfig = {
    Auth: {
      Cognito: {
        userPoolId: import.meta.env.VITE_USER_POOL_ID || 'us-east-1_dummy_pool',
        userPoolClientId: import.meta.env.VITE_APP_CLIENT_ID || 'dummy_client',
      }
    },
    API: {
      REST: {
        AiBuddyApi: {
          endpoint: (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, ''),
          region: import.meta.env.VITE_REGION || 'us-east-1'
        }
      }
    }
  };
