const mysql = require('mysql2/promise');
const path = require('path');

// Load .env from parent directory
require('dotenv').config({ path: path.join(__dirname, '../../.env') });

let pool = null;

/**
 * Get configuration from environment variables
 */
function getConfig() {
    return {
        app_ids: process.env.CHZZK_APP_IDS ? process.env.CHZZK_APP_IDS.split(',').map(s => s.trim()) : [],
        master_tokens: process.env.SOCKET_SERVER_MASTER_TOKEN ? process.env.SOCKET_SERVER_MASTER_TOKEN.split(',').map(s => s.trim()) : [],
        client_socket_port: parseInt(process.env.SOCKET_SERVER_PORT) || 3100,
        database: {
            host: process.env.DB_HOST || 'localhost',
            port: parseInt(process.env.DB_PORT) || 3306,
            user: process.env.DB_USER || 'root',
            password: process.env.DB_PASSWORD || '',
            database: process.env.DB_NAME || 'songbook'
        },
        chzzk_api_base: process.env.CHZZK_API_BASE || 'https://openapi.chzzk.naver.com'
    };
}

/**
 * Initialize database connection pool
 */
async function initDatabase() {
    const config = getConfig();
    pool = mysql.createPool({
        host: config.database.host,
        port: config.database.port,
        user: config.database.user,
        password: config.database.password,
        database: config.database.database,
        waitForConnections: true,
        connectionLimit: 10,
        queueLimit: 0
    });
    
    // Test connection
    const connection = await pool.getConnection();
    console.log('[DB] Database connected successfully');
    connection.release();
    
    return pool;
}

/**
 * Get streamers with their Chzzk tokens for specified app_ids
 * @param {string[]} appIds - List of app_ids to filter by
 * @returns {Promise<Array>} List of streamers with tokens
 */
async function getStreamersWithTokens(appIds) {
    if (!pool) throw new Error('Database not initialized');
    if (!appIds || appIds.length === 0) return [];
    
    const placeholders = appIds.map(() => '?').join(',');
    const query = `
        SELECT 
            s.id as streamer_id,
            s.user_id,
            s.streamer_id as external_streamer_id,
            s.slug,
            s.token as streamer_token,
            uct.channel_id,
            uct.channel_name,
            uct.access_token,
            uct.refresh_token,
            uct.expires_at,
            uct.app_id,
            cac.client_id,
            cac.client_secret
        FROM streamers s
        INNER JOIN user_chzzk_tokens uct ON s.user_id = uct.user_id
        INNER JOIN chzzk_app_config cac ON uct.app_id = cac.app_id
        WHERE uct.app_id IN (${placeholders})
    `;
    
    const [rows] = await pool.execute(query, appIds);
    return rows;
}

/**
 * Get streamer by their unique token
 * @param {string} token - Streamer token from streamers table
 * @returns {Promise<Object|null>} Streamer info or null
 */
async function getStreamerByToken(token) {
    if (!pool) throw new Error('Database not initialized');
    if (!token) return null;
    
    const query = `
        SELECT 
            s.id as streamer_id,
            s.user_id,
            s.streamer_id as external_streamer_id,
            s.slug,
            s.token as streamer_token,
            uct.channel_id
        FROM streamers s
        LEFT JOIN user_chzzk_tokens uct ON s.user_id = uct.user_id
        WHERE s.token = ?
        LIMIT 1
    `;
    
    const [rows] = await pool.execute(query, [token]);
    return rows.length > 0 ? rows[0] : null;
}

/**
 * Get app configuration by app_id
 * @param {string} appId - App ID
 * @returns {Promise<Object|null>} App config or null
 */
async function getAppConfig(appId) {
    if (!pool) throw new Error('Database not initialized');
    
    const query = `
        SELECT app_id, app_name, client_id, client_secret, redirect_uri
        FROM chzzk_app_config
        WHERE app_id = ?
        LIMIT 1
    `;
    
    const [rows] = await pool.execute(query, [appId]);
    return rows.length > 0 ? rows[0] : null;
}

/**
 * Update access token for a user
 * @param {number} userId - User ID
 * @param {string} appId - App ID
 * @param {string} accessToken - New access token
 * @param {string} refreshToken - New refresh token
 * @param {number} expiresAt - Expiration timestamp
 */
async function updateToken(userId, appId, accessToken, refreshToken, expiresAt) {
    if (!pool) throw new Error('Database not initialized');
    
    const query = `
        UPDATE user_chzzk_tokens
        SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND app_id = ?
    `;
    
    await pool.execute(query, [accessToken, refreshToken, expiresAt, userId, appId]);
}

/**
 * Get all streamer channel IDs
 * @returns {Promise<Array>} List of channel IDs
 */
async function getAllChannelIds() {
    if (!pool) throw new Error('Database not initialized');
    
    const query = `
        SELECT DISTINCT uct.channel_id
        FROM user_chzzk_tokens uct
        INNER JOIN streamers s ON s.user_id = uct.user_id
    `;
    
    const [rows] = await pool.execute(query);
    return rows.map(row => row.channel_id);
}

module.exports = {
    getConfig,
    initDatabase,
    getStreamersWithTokens,
    getStreamerByToken,
    getAppConfig,
    updateToken,
    getAllChannelIds
};
