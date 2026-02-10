const { Server } = require('socket.io');
const { createServer } = require('http');
const { getConfig, getStreamerByToken } = require('./db');

/**
 * Client Socket Server - Provides events to external clients
 */
class ClientServer {
    constructor(sessionManager) {
        this.sessionManager = sessionManager;
        this.io = null;
        this.httpServer = null;
        
        // Client tracking
        this.clients = new Map(); // socketId -> { socket, token, subscribedChannels, isMaster, subscribedAll }
        this.channelSubscribers = new Map(); // channelId -> Set of socketIds
        this.allSubscribers = new Set(); // socketIds subscribed to 'all'
        
        // Status broadcast interval
        this.statusInterval = null;
    }

    /**
     * Start the socket server
     */
    async start(port) {
        const config = getConfig();
        const serverPort = port || config.client_socket_port || 3100;
        
        this.httpServer = createServer();
        this.io = new Server(this.httpServer, {
            cors: {
                origin: '*',
                methods: ['GET', 'POST']
            }
        });

        this.setupEventHandlers();
        this.setupSessionManagerEvents();
        this.startStatusBroadcast();

        return new Promise((resolve) => {
            this.httpServer.listen(serverPort, () => {
                console.log(`[ClientServer] Listening on port ${serverPort}`);
                resolve();
            });
        });
    }

    /**
     * Setup Socket.IO event handlers
     */
    setupEventHandlers() {
        const config = getConfig();
        
        this.io.on('connection', async (socket) => {
            const token = socket.handshake.auth?.token;
            
            if (!token) {
                console.log(`[ClientServer] Connection rejected - no token provided`);
                socket.emit('error', { message: 'Authentication required' });
                socket.disconnect();
                return;
            }

            // Check if master token
            const masterTokens = config.master_tokens || [];
            const isMaster = masterTokens.includes(token);
            
            let streamerInfo = null;
            let allowedChannelId = null;
            
            if (!isMaster) {
                // Validate streamer token
                streamerInfo = await getStreamerByToken(token);
                if (!streamerInfo) {
                    console.log(`[ClientServer] Connection rejected - invalid token`);
                    socket.emit('error', { message: 'Invalid token' });
                    socket.disconnect();
                    return;
                }
                allowedChannelId = streamerInfo.channel_id;
            }

            // Register client
            this.clients.set(socket.id, {
                socket,
                token,
                streamerInfo,
                allowedChannelId,
                isMaster,
                subscribedChannels: new Set(),
                subscribedAll: false
            });

            console.log(`[ClientServer] Client connected: ${socket.id} (master: ${isMaster})`);
            socket.emit('connected', { 
                message: 'Connected successfully',
                isMaster,
                allowedChannelId
            });

            // Handle subscribe event
            socket.on('subscribe', (data) => this.handleSubscribe(socket, data));
            
            // Handle unsubscribe event
            socket.on('unsubscribe', (data) => this.handleUnsubscribe(socket, data));
            
            // Handle disconnect
            socket.on('disconnect', () => this.handleDisconnect(socket));
        });
    }

    /**
     * Handle subscription request
     */
    handleSubscribe(socket, data) {
        const client = this.clients.get(socket.id);
        if (!client) return;

        const channelId = data?.channelId || data?.channel_id;
        
        // Special case: subscribe to 'all' (master only)
        if (channelId === 'all') {
            if (!client.isMaster) {
                socket.emit('error', { message: 'Only master tokens can subscribe to all' });
                return;
            }
            
            client.subscribedAll = true;
            this.allSubscribers.add(socket.id);
            socket.emit('subscribed', { channelId: 'all' });
            console.log(`[ClientServer] Client ${socket.id} subscribed to 'all'`);
            
            // Broadcast to other 'all' subscribers
            this.broadcastClientActivity('subscribe', socket.id, 'all');
            return;
        }

        // Check if channel exists
        if (!this.sessionManager.hasChannel(channelId)) {
            socket.emit('error', { message: `Channel ${channelId} not found` });
            return;
        }

        // Check permission (master can subscribe to any, regular users only to their own)
        if (!client.isMaster && client.allowedChannelId !== channelId) {
            socket.emit('error', { message: 'Not authorized to subscribe to this channel' });
            return;
        }

        // Add subscription
        client.subscribedChannels.add(channelId);
        
        if (!this.channelSubscribers.has(channelId)) {
            this.channelSubscribers.set(channelId, new Set());
        }
        this.channelSubscribers.get(channelId).add(socket.id);

        socket.emit('subscribed', { channelId });
        console.log(`[ClientServer] Client ${socket.id} subscribed to channel ${channelId}`);
        
        // Broadcast to 'all' subscribers
        this.broadcastClientActivity('subscribe', socket.id, channelId);
    }

    /**
     * Handle unsubscription request
     */
    handleUnsubscribe(socket, data) {
        const client = this.clients.get(socket.id);
        if (!client) return;

        const channelId = data?.channelId || data?.channel_id;

        if (channelId === 'all') {
            client.subscribedAll = false;
            this.allSubscribers.delete(socket.id);
            socket.emit('unsubscribed', { channelId: 'all' });
            console.log(`[ClientServer] Client ${socket.id} unsubscribed from 'all'`);
            
            this.broadcastClientActivity('unsubscribe', socket.id, 'all');
            return;
        }

        client.subscribedChannels.delete(channelId);
        
        const subscribers = this.channelSubscribers.get(channelId);
        if (subscribers) {
            subscribers.delete(socket.id);
        }

        socket.emit('unsubscribed', { channelId });
        console.log(`[ClientServer] Client ${socket.id} unsubscribed from channel ${channelId}`);
        
        this.broadcastClientActivity('unsubscribe', socket.id, channelId);
    }

    /**
     * Handle client disconnect
     */
    handleDisconnect(socket) {
        const client = this.clients.get(socket.id);
        if (!client) return;

        // Clean up subscriptions
        for (const channelId of client.subscribedChannels) {
            const subscribers = this.channelSubscribers.get(channelId);
            if (subscribers) {
                subscribers.delete(socket.id);
            }
        }

        // Clean up 'all' subscription
        this.allSubscribers.delete(socket.id);

        this.clients.delete(socket.id);
        console.log(`[ClientServer] Client disconnected: ${socket.id}`);
        
        // Broadcast to 'all' subscribers
        this.broadcastClientActivity('disconnect', socket.id, null);
    }

    /**
     * Setup event handlers for SessionManager
     */
    setupSessionManagerEvents() {
        this.sessionManager.on('chat', (data) => {
            this.broadcastEvent('chat', data);
        });

        this.sessionManager.on('donation', (data) => {
            this.broadcastEvent('donation', data);
        });

        this.sessionManager.on('subscription', (data) => {
            this.broadcastEvent('subscription', data);
        });
    }

    /**
     * Broadcast event to subscribed clients
     */
    broadcastEvent(eventType, data) {
        const channelId = data.channelId;
        
        // Send to channel subscribers
        const subscribers = this.channelSubscribers.get(channelId);
        if (subscribers) {
            for (const socketId of subscribers) {
                const client = this.clients.get(socketId);
                if (client) {
                    client.socket.emit(eventType, data);
                }
            }
        }

        // Send to 'all' subscribers
        for (const socketId of this.allSubscribers) {
            const client = this.clients.get(socketId);
            if (client) {
                client.socket.emit(eventType, data);
            }
        }
    }

    /**
     * Broadcast client activity to 'all' subscribers
     */
    broadcastClientActivity(action, clientId, channelId) {
        const message = {
            type: 'client_activity',
            data: {
                action,
                client_id: clientId,
                streamer_uid: channelId
            },
            timestamp: Date.now()
        };

        for (const socketId of this.allSubscribers) {
            // Don't send to self
            if (socketId === clientId) continue;
            
            const client = this.clients.get(socketId);
            if (client) {
                client.socket.emit('client_activity', message);
            }
        }
    }

    /**
     * Start status broadcast interval (every 30 seconds)
     */
    startStatusBroadcast() {
        this.statusInterval = setInterval(() => {
            if (this.allSubscribers.size === 0) return;

            const stats = this.sessionManager.getStats();
            const message = {
                type: 'status',
                data: {
                    total_connected_streamers: stats.total_connected_streamers,
                    total_connected_clients: this.clients.size,
                    failed_streamers: stats.failed_streamers
                },
                timestamp: Date.now()
            };

            for (const socketId of this.allSubscribers) {
                const client = this.clients.get(socketId);
                if (client) {
                    client.socket.emit('status', message);
                }
            }
        }, 30000); // 30 seconds
    }

    /**
     * Get server statistics
     */
    getStats() {
        return {
            connectedClients: this.clients.size,
            allSubscribers: this.allSubscribers.size,
            channelSubscriptions: this.channelSubscribers.size
        };
    }

    /**
     * Stop the server
     */
    async stop() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
            this.statusInterval = null;
        }

        if (this.io) {
            this.io.close();
        }

        if (this.httpServer) {
            return new Promise((resolve) => {
                this.httpServer.close(resolve);
            });
        }
    }
}

module.exports = ClientServer;
