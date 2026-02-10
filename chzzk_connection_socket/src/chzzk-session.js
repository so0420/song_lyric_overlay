const io = require('socket.io-client');
const axios = require('axios');
const EventEmitter = require('events');
const { getConfig } = require('./db');

/**
 * Individual Chzzk Session for a single streamer
 * Manages WebSocket connection and event subscriptions
 */
class ChzzkSession extends EventEmitter {
    constructor(streamerInfo) {
        super();
        this.streamerInfo = streamerInfo;
        this.channelId = streamerInfo.channel_id;
        this.accessToken = streamerInfo.access_token;
        this.refreshToken = streamerInfo.refresh_token;
        this.expiresAt = streamerInfo.expires_at;
        this.clientId = streamerInfo.client_id;
        this.clientSecret = streamerInfo.client_secret;

        this.socket = null;
        this.sessionKey = null;
        this.isConnected = false;
        this.isSubscribed = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // Start with 1 second
        this.reconnectTimer = null;

        this.config = getConfig();
    }

    /**
     * Get authorization header for API requests
     */
    getAuthHeader() {
        return {
            'Authorization': `Bearer ${this.accessToken}`,
            'Content-Type': 'application/json'
        };
    }

    /**
     * Refresh access token if expired
     */
    async refreshAccessToken() {
        const now = Math.floor(Date.now() / 1000);
        if (this.expiresAt > now + 300) { // 5 minutes buffer
            return true;
        }

        try {
            console.log(`[Session:${this.channelId}] Refreshing access token...`);
            const response = await axios.post('https://auth.chzzk.naver.com/v1/token', {
                grant_type: 'refresh_token',
                refresh_token: this.refreshToken,
                client_id: this.clientId,
                client_secret: this.clientSecret
            });

            if (response.data.access_token) {
                this.accessToken = response.data.access_token;
                this.refreshToken = response.data.refresh_token || this.refreshToken;
                this.expiresAt = Math.floor(Date.now() / 1000) + response.data.expires_in;

                // Emit event to update database
                this.emit('tokenRefreshed', {
                    userId: this.streamerInfo.user_id,
                    appId: this.streamerInfo.app_id,
                    accessToken: this.accessToken,
                    refreshToken: this.refreshToken,
                    expiresAt: this.expiresAt
                });

                console.log(`[Session:${this.channelId}] Token refreshed successfully`);
                return true;
            }
        } catch (error) {
            console.error(`[Session:${this.channelId}] Failed to refresh token:`, error.message);
            return false;
        }
        return false;
    }

    /**
     * Create a new session and get WebSocket URL
     */
    async createSession() {
        try {
            await this.refreshAccessToken();

            console.log(`[Session:${this.channelId}] Creating session...`);
            console.log(`[Session:${this.channelId}] API URL: ${this.config.chzzk_api_base}/open/v1/sessions/auth`);
            console.log(`[Session:${this.channelId}] Token (first 20 chars): ${this.accessToken?.substring(0, 20)}...`);

            const response = await axios.get(
                `${this.config.chzzk_api_base}/open/v1/sessions/auth`,
                {
                    headers: {
                        ...this.getAuthHeader(),
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    },
                    timeout: 30000  // 30초 타임아웃
                }
            );

            console.log(`[Session:${this.channelId}] Response status: ${response.status}`);
            console.log(`[Session:${this.channelId}] Response data:`, JSON.stringify(response.data, null, 2));

            if (response.data.code === 200 && response.data.content?.url) {
                console.log(`[Session:${this.channelId}] Session URL obtained successfully`);
                return response.data.content.url;
            } else {
                throw new Error(`Session creation failed: code=${response.data.code}, message=${response.data.message}`);
            }
        } catch (error) {
            if (error.response) {
                // HTTP 에러 응답
                console.error(`[Session:${this.channelId}] HTTP Error: ${error.response.status}`);
                console.error(`[Session:${this.channelId}] Response headers:`, JSON.stringify(error.response.headers, null, 2));
                console.error(`[Session:${this.channelId}] Response data:`, JSON.stringify(error.response.data, null, 2));
            } else if (error.request) {
                // 요청은 보냈지만 응답 없음
                console.error(`[Session:${this.channelId}] No response received`);
                console.error(`[Session:${this.channelId}] Request details:`, error.message);
            } else {
                // 기타 에러
                console.error(`[Session:${this.channelId}] Error:`, error.message);
            }
            throw error;
        }
    }

    /**
     * Subscribe to events (chat, donation, subscription)
     */
    async subscribeToEvents() {
        if (!this.sessionKey) {
            console.error(`[Session:${this.channelId}] No session key, cannot subscribe`);
            return false;
        }

        const headers = this.getAuthHeader();
        const eventTypes = ['chat', 'donation', 'subscription'];

        for (const eventType of eventTypes) {
            try {
                const response = await axios.post(
                    `${this.config.chzzk_api_base}/open/v1/sessions/events/subscribe/${eventType}`,
                    null,
                    {
                        headers,
                        params: { sessionKey: this.sessionKey }
                    }
                );

                if (response.data.code === 200) {
                    console.log(`[Session:${this.channelId}] Subscribed to ${eventType}`);
                } else {
                    console.warn(`[Session:${this.channelId}] Failed to subscribe to ${eventType}:`, response.data);
                }
            } catch (error) {
                console.error(`[Session:${this.channelId}] Error subscribing to ${eventType}:`, error.message);
            }
        }

        this.isSubscribed = true;
        return true;
    }

    /**
     * Connect to Chzzk WebSocket
     */
    async connect() {
        // 기존 소켓이 있으면 먼저 정리 (세션 누적 방지)
        if (this.socket) {
            console.log(`[Session:${this.channelId}] Cleaning up existing socket before reconnect...`);
            this.socket.removeAllListeners();
            this.socket.disconnect();
            this.socket = null;
        }

        let socketUrl;
        try {
            socketUrl = await this.createSession();
        } catch (error) {
            console.error(`[Session:${this.channelId}] Failed to create session:`, error.message);
            this.scheduleReconnect();
            return;
        }

        console.log(`[Session:${this.channelId}] Connecting to WebSocket...`);

        // Socket.IO 2.0.3 connection
        this.socket = io(socketUrl, {
            transports: ['websocket'],
            reconnection: false // We handle reconnection manually
        });

        this.socket.on('connect', () => {
            console.log(`[Session:${this.channelId}] WebSocket connected`);
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
        });

        // Socket.IO v2.x에서는 onAny()가 지원되지 않으므로 개별 이벤트로 처리
        // SYSTEM, CHAT, DONATION, SUBSCRIPTION 이벤트 리스너
        this.socket.on('SYSTEM', (data) => {
            console.log(`[Session:${this.channelId}] SYSTEM event:`, typeof data === 'string' ? data.substring(0, 200) : JSON.stringify(data).substring(0, 200));
            // 문자열로 올 경우 파싱
            const parsed = typeof data === 'string' ? JSON.parse(data) : data;
            this.handleSystemMessage(parsed);
        });

        this.socket.on('CHAT', (data) => {
            console.log(`[Session:${this.channelId}] CHAT event received`);
            this.emit('chat', {
                channelId: this.channelId,
                channelName: this.streamerInfo.channel_name,
                data: data
            });
        });

        this.socket.on('DONATION', (data) => {
            console.log(`[Session:${this.channelId}] DONATION event received`);
            this.emit('donation', {
                channelId: this.channelId,
                channelName: this.streamerInfo.channel_name,
                data: data
            });
        });

        this.socket.on('SUBSCRIPTION', (data) => {
            console.log(`[Session:${this.channelId}] SUBSCRIPTION event received`);
            this.emit('subscription', {
                channelId: this.channelId,
                channelName: this.streamerInfo.channel_name,
                data: data
            });
        });

        // 레거시 message 이벤트도 유지 (혹시 서버가 이 형식으로 보내는 경우)
        this.socket.on('message', (data) => {
            console.log(`[Session:${this.channelId}] Message event received`);
            this.handleMessage(data);
        });

        this.socket.on('disconnect', (reason) => {
            console.log(`[Session:${this.channelId}] Disconnected: ${reason}`);
            this.isConnected = false;
            this.isSubscribed = false;
            this.sessionKey = null;
            this.scheduleReconnect();
        });

        this.socket.on('error', (error) => {
            console.error(`[Session:${this.channelId}] Socket error:`, error);
        });

        this.socket.on('connect_error', (error) => {
            console.error(`[Session:${this.channelId}] Connection error:`, error.message);
            this.isConnected = false;
            this.scheduleReconnect();
        });
    }

    /**
     * Handle incoming messages
     */
    handleMessage(data) {
        try {
            const message = typeof data === 'string' ? JSON.parse(data) : data;

            // System messages
            if (message.type === 'SYSTEM' || message.eventType === 'SYSTEM') {
                this.handleSystemMessage(message);
                return;
            }

            // Event messages
            const eventType = message.eventType || message.type;

            switch (eventType) {
                case 'CHAT':
                    this.emit('chat', {
                        channelId: this.channelId,
                        channelName: this.streamerInfo.channel_name,
                        data: message
                    });
                    break;

                case 'DONATION':
                    this.emit('donation', {
                        channelId: this.channelId,
                        channelName: this.streamerInfo.channel_name,
                        data: message
                    });
                    break;

                case 'SUBSCRIPTION':
                    this.emit('subscription', {
                        channelId: this.channelId,
                        channelName: this.streamerInfo.channel_name,
                        data: message
                    });
                    break;

                default:
                    console.log(`[Session:${this.channelId}] Unknown event type:`, eventType, message);
            }
        } catch (error) {
            console.error(`[Session:${this.channelId}] Error handling message:`, error);
        }
    }

    /**
     * Handle system messages
     */
    handleSystemMessage(message) {
        const systemType = message.data?.type || message.type;

        switch (systemType) {
            case 'connected':
                this.sessionKey = message.data?.sessionKey;
                console.log(`[Session:${this.channelId}] Session key received: ${this.sessionKey}`);
                // Subscribe to events after connection
                this.subscribeToEvents();
                break;

            case 'subscribed':
                console.log(`[Session:${this.channelId}] Event subscribed:`, message.data?.eventType);
                break;

            case 'unsubscribed':
                console.log(`[Session:${this.channelId}] Event unsubscribed:`, message.data?.eventType);
                break;

            case 'revoked':
                console.warn(`[Session:${this.channelId}] Permission revoked:`, message.data?.eventType);
                break;

            default:
                console.log(`[Session:${this.channelId}] System message:`, message);
        }
    }

    /**
     * Schedule reconnection with exponential backoff
     */
    scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`[Session:${this.channelId}] Max reconnect attempts reached`);
            this.emit('maxReconnectReached', { channelId: this.channelId });
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), 60000); // Max 60 seconds

        console.log(`[Session:${this.channelId}] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, delay);
    }

    /**
     * Disconnect from WebSocket
     */
    disconnect() {
        // 의도적인 종료 플래그 설정 (재연결 방지)
        this._isIntentionalDisconnect = true;

        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.socket) {
            // 이벤트 리스너 먼저 제거 (disconnect 이벤트가 scheduleReconnect 호출하는 것 방지)
            this.socket.removeAllListeners();
            this.socket.disconnect();
            this.socket = null;
        }

        this.isConnected = false;
        this.isSubscribed = false;
        this.sessionKey = null;

        console.log(`[Session:${this.channelId}] Session disconnected (intentional)`);
    }

    /**
     * Get connection status
     */
    getStatus() {
        return {
            channelId: this.channelId,
            channelName: this.streamerInfo.channel_name,
            isConnected: this.isConnected,
            isSubscribed: this.isSubscribed,
            reconnectAttempts: this.reconnectAttempts
        };
    }
}

module.exports = ChzzkSession;
