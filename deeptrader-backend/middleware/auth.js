/**
 * Authentication Middleware
 * JWT token verification and user authentication
 */

import jwt from 'jsonwebtoken';
import { findUserById } from '../models/User.js';
import redisState from '../services/redisState.js';
import crypto from 'crypto';
import pool from '../config/database.js';

const JWT_SECRET = process.env.JWT_SECRET || 'your-secret-key-change-in-production';

/**
 * Verify JWT token and attach user to request
 */
export const authenticateToken = async (req, res, next) => {
  try {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1]; // Bearer TOKEN

    if (!token) {
      return res.status(401).json({ error: 'Access token required' });
    }

    // Verify token
    const decoded = jwt.verify(token, JWT_SECRET);

    // Check if user exists and is active
    const user = await findUserById(decoded.userId);
    if (!user) {
      return res.status(401).json({ error: 'User not found' });
    }

    // Check if session is valid (optional - for enhanced security)
    if (process.env.CHECK_SESSIONS === 'true') {
      const tokenHash = require('crypto').createHash('sha256').update(token).digest('hex');
      const sessionQuery = 'SELECT * FROM user_sessions WHERE user_id = $1 AND token_hash = $2 AND expires_at > CURRENT_TIMESTAMP';
      const sessionResult = await pool.query(sessionQuery, [user.id, tokenHash]);

      if (sessionResult.rows.length === 0) {
        return res.status(401).json({ error: 'Session expired or invalid' });
      }
    }

    // Attach user to request
    req.user = user;
    next();
  } catch (error) {
    if (error.name === 'JsonWebTokenError') {
      return res.status(401).json({ error: 'Invalid token' });
    } else if (error.name === 'TokenExpiredError') {
      return res.status(401).json({ error: 'Token expired' });
    }

    console.error('Auth middleware error:', error);
    return res.status(500).json({ error: 'Authentication error' });
  }
};

/**
 * Check if user has required role
 */
export const requireRole = (roles) => {
  return (req, res, next) => {
    if (!req.user) {
      return res.status(401).json({ error: 'Authentication required' });
    }

    const userRole = req.user.role || 'user';
    const allowedRoles = Array.isArray(roles) ? roles : [roles];

    if (!allowedRoles.includes(userRole)) {
      return res.status(403).json({ error: 'Insufficient permissions' });
    }

    next();
  };
};

/**
 * Optional authentication - doesn't fail if no token
 */
export const optionalAuth = async (req, res, next) => {
  try {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];

    if (token) {
      const decoded = jwt.verify(token, JWT_SECRET);
      const user = await findUserById(decoded.userId);
      if (user) {
        req.user = user;
      }
    }

    next();
  } catch (error) {
    // Ignore auth errors for optional auth
    next();
  }
};

/**
 * Rate limiting helper (basic implementation)
 */
const rateLimitStore = new Map();

export const rateLimit = (windowMs = 15 * 60 * 1000, maxRequests = 100) => {
  return (req, res, next) => {
    // Get IP address (handle proxies)
    const key = req.ip || 
                req.headers['x-forwarded-for']?.split(',')[0]?.trim() || 
                req.connection?.remoteAddress || 
                'unknown';
    
    const now = Date.now();
    const windowStart = now - windowMs;

    // Get or create rate limit data for this IP
    let userRequests = rateLimitStore.get(key) || [];

    // Remove old requests outside the window
    userRequests = userRequests.filter(timestamp => timestamp > windowStart);

    // Check if under limit
    if (userRequests.length >= maxRequests) {
      const retryAfter = userRequests.length > 0 
        ? Math.ceil((userRequests[0] + windowMs - now) / 1000)
        : Math.ceil(windowMs / 1000);
      
      return res.status(429).json({
        error: 'Too many requests',
        message: `Rate limit exceeded: ${maxRequests} requests per ${Math.floor(windowMs / 60000)} minutes`,
        retryAfter
      });
    }

    // Add current request
    userRequests.push(now);
    rateLimitStore.set(key, userRequests);

    next();
  };
};

/**
 * API key authentication for external services
 */
export const authenticateApiKey = (req, res, next) => {
  const apiKey = req.headers['x-api-key'] || req.query.apiKey;

  if (!apiKey || apiKey !== process.env.INTERNAL_API_KEY) {
    return res.status(401).json({ error: 'Invalid API key' });
  }

  next();
};

/**
 * User-scoped API key authentication using stored hashed keys in settings
 * Requires x-api-key header and x-user-id (or user_id) to avoid scanning all users.
 */
export const authenticateUserApiKey = async (req, res, next) => {
  try {
    const apiKey = req.headers['x-api-key'] || req.query.apiKey;
    const userId = req.headers['x-user-id'] || req.query.user_id;
    if (!apiKey || !userId) {
      return res.status(401).json({ error: 'API key and user id required' });
    }
    const hash = crypto.createHash('sha256').update(apiKey).digest('hex');
    const keys = await redisState.getUserJson(userId, 'settings_api_keys', []);
    const idx = keys.findIndex((k) => k.hash === hash);
    if (idx === -1) {
      return res.status(401).json({ error: 'Invalid API key' });
    }
    const user = await findUserById(userId);
    if (!user) return res.status(401).json({ error: 'User not found' });
    const now = new Date().toISOString();
    keys[idx].lastUsedAt = now;
    await redisState.setUserJson(userId, 'settings_api_keys', keys);
    req.user = user;
    next();
  } catch (error) {
    console.error('User API key auth error:', error);
    return res.status(500).json({ error: 'Authentication error' });
  }
};

const VIEWER_ALLOWED_CORE_PATHS = new Set([
  '/health',
  '/auth/me',
  '/auth/logout',
]);

/**
 * Viewer accounts are read-only and should not reach core management APIs.
 */
export const enforceViewerCoreAccess = async (req, res, next) => {
  try {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];
    if (!token) {
      return next();
    }

    const decoded = jwt.verify(token, JWT_SECRET);
    if ((decoded?.role || '').toLowerCase() !== 'viewer') {
      return next();
    }

    const user = await findUserById(decoded.userId);
    if (!user) {
      return res.status(401).json({ error: 'User not found' });
    }

    req.user = user;

    if (VIEWER_ALLOWED_CORE_PATHS.has(req.path)) {
      return next();
    }

    return res.status(403).json({ error: 'Viewer accounts are read-only' });
  } catch (_error) {
    return next();
  }
};
