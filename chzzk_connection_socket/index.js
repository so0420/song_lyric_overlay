const { initDatabase, getConfig } = require('./src/db');
const { getSessionManager } = require('./src/session-manager');
const ClientServer = require('./src/client-server');

/**
 * Chzzk Connection Socket Service
 * 
 * Main entry point for the service that:
 * 1. Connects to all registered streamers' Chzzk chat
 * 2. Subscribes to chat, donation, and subscription events
 * 3. Provides a Socket.IO server for external clients to receive events
 */

async function main() {
    console.log('='.repeat(60));
    console.log('Chzzk Connection Socket Service');
    console.log('='.repeat(60));
    
    try {
        // Initialize database connection
        console.log('[Main] Initializing database...');
        await initDatabase();
        
        // Get config after DB is initialized
        const config = getConfig();
        
        // Initialize session manager
        console.log('[Main] Initializing session manager...');
        const sessionManager = getSessionManager();
        await sessionManager.initialize();
        
        // Start client server
        console.log('[Main] Starting client server...');
        const clientServer = new ClientServer(sessionManager);
        await clientServer.start(config.client_socket_port);
        
        console.log('='.repeat(60));
        console.log('[Main] Service started successfully');
        console.log(`[Main] App IDs: ${config.app_ids.join(', ') || '(none)'}`);
        console.log(`[Main] Master tokens configured: ${config.master_tokens?.length || 0}`);
        console.log(`[Main] Client socket port: ${config.client_socket_port}`);
        console.log('='.repeat(60));
        
        // Handle graceful shutdown
        process.on('SIGINT', async () => {
            console.log('\n[Main] Shutting down...');
            sessionManager.disconnectAll();
            await clientServer.stop();
            console.log('[Main] Goodbye!');
            process.exit(0);
        });
        
        process.on('SIGTERM', async () => {
            console.log('\n[Main] Shutting down...');
            sessionManager.disconnectAll();
            await clientServer.stop();
            process.exit(0);
        });
        
        // Periodic retry for failed connections (every 5 minutes)
        setInterval(async () => {
            const stats = sessionManager.getStats();
            if (stats.failed_streamers > 0) {
                console.log(`[Main] Retrying ${stats.failed_streamers} failed connections...`);
                await sessionManager.retryFailed();
            }
        }, 5 * 60 * 1000);
        
    } catch (error) {
        console.error('[Main] Fatal error:', error);
        process.exit(1);
    }
}

main();
