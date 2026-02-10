const EventEmitter = require('events');
const ChzzkSession = require('./chzzk-session');
const { getConfig, getStreamersWithTokens, updateToken } = require('./db');

/**
 * Session Manager - Manages all Chzzk sessions for registered streamers
 */
class SessionManager extends EventEmitter {
    constructor() {
        super();
        this.sessions = new Map(); // channelId -> ChzzkSession
        this.streamerMap = new Map(); // channelId -> streamerInfo
        this.failedStreamers = new Set(); // Set of channelIds that failed to connect
        this.refreshInterval = null; // Interval for periodic refresh
    }

    /**
     * Initialize and start all sessions
     */
    async initialize() {
        console.log('[SessionManager] Initializing...');
        
        const config = getConfig();
        const appIds = config.app_ids || [];
        if (appIds.length === 0) {
            console.warn('[SessionManager] No app_ids configured (CHZZK_APP_IDS)');
            return;
        }
        
        const streamers = await getStreamersWithTokens(appIds);
        console.log(`[SessionManager] Found ${streamers.length} streamers to connect`);
        
        for (const streamer of streamers) {
            await this.addSession(streamer);
        }
        
        console.log(`[SessionManager] Initialized with ${this.sessions.size} sessions`);
        
        // Start periodic refresh (every 1 second)
        this.startPeriodicRefresh();
    }

    /**
     * Start periodic refresh of streamers from database
     */
    startPeriodicRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }

        this.refreshInterval = setInterval(async () => {
            await this.refreshStreamers();
        }, 1000); // 1 second

        console.log('[SessionManager] Started periodic refresh (1s interval)');
    }

    /**
     * Stop periodic refresh
     */
    stopPeriodicRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
            console.log('[SessionManager] Stopped periodic refresh');
        }
    }

    /**
     * Refresh streamers from database - add new ones, remove deleted ones
     */
    async refreshStreamers() {
        try {
            const config = getConfig();
            const appIds = config.app_ids || [];
            if (appIds.length === 0) return;

            const streamers = await getStreamersWithTokens(appIds);
            const dbChannelIds = new Set(streamers.map(s => s.channel_id));

            // Find and add new streamers
            for (const streamer of streamers) {
                if (!this.sessions.has(streamer.channel_id)) {
                    console.log(`[SessionManager] New streamer detected: ${streamer.channel_id}`);
                    await this.addSession(streamer);
                }
            }

            // Find and remove deleted streamers
            const currentChannelIds = Array.from(this.sessions.keys());
            for (const channelId of currentChannelIds) {
                if (!dbChannelIds.has(channelId)) {
                    console.log(`[SessionManager] Streamer removed from DB: ${channelId}, disconnecting...`);
                    this.removeSession(channelId);
                }
            }
        } catch (error) {
            console.error('[SessionManager] Error refreshing streamers:', error.message);
        }
    }

    /**
     * Add a new session for a streamer
     */
    async addSession(streamerInfo) {
        const channelId = streamerInfo.channel_id;
        
        if (this.sessions.has(channelId)) {
            console.log(`[SessionManager] Session already exists for ${channelId}`);
            return;
        }
        
        this.streamerMap.set(channelId, streamerInfo);
        
        const session = new ChzzkSession(streamerInfo);
        
        // Forward events
        session.on('chat', (data) => {
            this.emit('chat', data);
        });
        
        session.on('donation', (data) => {
            this.emit('donation', data);
        });
        
        session.on('subscription', (data) => {
            this.emit('subscription', data);
        });
        
        // Handle token refresh
        session.on('tokenRefreshed', async (tokenData) => {
            try {
                await updateToken(
                    tokenData.userId,
                    tokenData.appId,
                    tokenData.accessToken,
                    tokenData.refreshToken,
                    tokenData.expiresAt
                );
                console.log(`[SessionManager] Token updated in database for user ${tokenData.userId}`);
            } catch (error) {
                console.error(`[SessionManager] Failed to update token:`, error);
            }
        });
        
        // Handle max reconnect reached
        session.on('maxReconnectReached', (data) => {
            this.failedStreamers.add(data.channelId);
            this.emit('sessionFailed', data);
        });
        
        this.sessions.set(channelId, session);
        
        // Start connection
        try {
            await session.connect();
            this.failedStreamers.delete(channelId);
        } catch (error) {
            console.error(`[SessionManager] Failed to connect session for ${channelId}:`, error);
            this.failedStreamers.add(channelId);
        }
    }

    /**
     * Remove a session
     */
    removeSession(channelId) {
        const session = this.sessions.get(channelId);
        if (session) {
            session.disconnect();
            this.sessions.delete(channelId);
            this.streamerMap.delete(channelId);
            this.failedStreamers.delete(channelId);
            console.log(`[SessionManager] Removed session for ${channelId}`);
        }
    }

    /**
     * Get session by channel ID
     */
    getSession(channelId) {
        return this.sessions.get(channelId);
    }

    /**
     * Get streamer info by channel ID
     */
    getStreamerInfo(channelId) {
        return this.streamerMap.get(channelId);
    }

    /**
     * Get all connected channel IDs
     */
    getConnectedChannelIds() {
        const connected = [];
        for (const [channelId, session] of this.sessions) {
            if (session.isConnected) {
                connected.push(channelId);
            }
        }
        return connected;
    }

    /**
     * Get status of all sessions
     */
    getStatus() {
        const statuses = [];
        for (const [channelId, session] of this.sessions) {
            statuses.push(session.getStatus());
        }
        return statuses;
    }

    /**
     * Get summary statistics
     */
    getStats() {
        let connected = 0;
        let disconnected = 0;
        
        for (const session of this.sessions.values()) {
            if (session.isConnected) {
                connected++;
            } else {
                disconnected++;
            }
        }
        
        return {
            total_connected_streamers: connected,
            total_streamers: this.sessions.size,
            failed_streamers: this.failedStreamers.size
        };
    }

    /**
     * Retry failed connections
     */
    async retryFailed() {
        for (const channelId of this.failedStreamers) {
            const session = this.sessions.get(channelId);
            if (session) {
                console.log(`[SessionManager] Retrying connection for ${channelId}`);
                session.reconnectAttempts = 0;
                await session.connect();
            }
        }
    }

    /**
     * Disconnect all sessions
     */
    disconnectAll() {
        this.stopPeriodicRefresh();
        for (const session of this.sessions.values()) {
            session.disconnect();
        }
        this.sessions.clear();
        this.streamerMap.clear();
        this.failedStreamers.clear();
        console.log('[SessionManager] All sessions disconnected');
    }

    /**
     * Check if a channel ID exists
     */
    hasChannel(channelId) {
        return this.sessions.has(channelId);
    }
}

// Singleton instance
let instance = null;

function getSessionManager() {
    if (!instance) {
        instance = new SessionManager();
    }
    return instance;
}

module.exports = {
    SessionManager,
    getSessionManager
};
