/**
 * User Model
 * Handles user authentication and profile management
 */

import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';
import { v4 as uuidv4 } from 'uuid';
import pool from '../config/database.js';

let _usersColumnsPromise = null;
async function getUsersColumns() {
  if (_usersColumnsPromise) return _usersColumnsPromise;
  _usersColumnsPromise = (async () => {
    const res = await pool.query(
      `select column_name
       from information_schema.columns
       where table_schema='public' and table_name='users'`
    );
    return new Set(res.rows.map((r) => r.column_name));
  })();
  return _usersColumnsPromise;
}

function deriveUsernameFromEmail(email) {
  const local = String(email || '').split('@')[0] || 'user';
  // Keep it simple: allow [a-z0-9_], enforce >= 3 chars like legacy.
  const cleaned = local.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_');
  const base = cleaned.length >= 3 ? cleaned : `${cleaned}${'user'.slice(0, 3 - cleaned.length)}`;
  return base.slice(0, 32);
}

export class User {
  constructor(data) {
    this.id = data.id;
    this.userId = data.id; // Alias for compatibility with routes using req.user.userId
    this.email = data.email;
    this.username = data.username ?? deriveUsernameFromEmail(data.email);
    // Support both schemas:
    // - newer: password_hash
    // - local base schema / AWS dev: encrypted_password
    this.passwordHash = data.password_hash ?? data.encrypted_password ?? null;
    // Legacy schema compatibility:
    // Older DBs store a single `name` column rather than `first_name`/`last_name`.
    this.firstName = data.first_name ?? null;
    this.lastName = data.last_name ?? null;
    if ((!this.firstName && !this.lastName) && typeof data.name === 'string' && data.name.trim()) {
      const parts = data.name.trim().split(/\s+/);
      this.firstName = parts[0] || null;
      this.lastName = parts.length > 1 ? parts.slice(1).join(' ') : null;
    }
    this.role = data.role;
    this.emailVerified = data.email_verified;
    this.isActive = data.is_active;
    this.lastLogin = data.last_login ?? data.last_sign_in_at ?? null;
    this.createdAt = data.created_at;
    this.updatedAt = data.updated_at;
    this.metadata = data.metadata ?? {};
    this.parentUserId = this.metadata?.parentUserId ?? null;
    this.viewerScope = this.metadata?.viewerScope ?? null;
    this.tenantId = this.parentUserId || this.id;
  }

  /**
   * Create a new user
   * @param {Object} userData - User data including email, username, password, firstName, lastName
   */
  static async create(userData) {
    const { email, username, password, firstName, lastName, role, metadata } = userData;

    // Hash password
    const saltRounds = 10;
    const passwordHash = await bcrypt.hash(password, saltRounds);

    const usersColumns = await getUsersColumns();
    const hasUsername = usersColumns.has('username');
    const passwordColumn = usersColumns.has('password_hash')
      ? 'password_hash'
      : (usersColumns.has('encrypted_password') ? 'encrypted_password' : null);
    if (!passwordColumn) {
      throw new Error('Unsupported users schema: missing password_hash/encrypted_password');
    }

    const effectiveUsername = (username && String(username).trim())
      ? String(username).trim()
      : deriveUsernameFromEmail(email);
    const name = [firstName, lastName].filter(Boolean).join(' ').trim() || effectiveUsername;

    const cols = ['email'];
    const vals = [email];
    if (hasUsername) {
      cols.push('username');
      vals.push(effectiveUsername);
    }
    cols.push(passwordColumn);
    vals.push(passwordHash);
    cols.push('name');
    vals.push(name);
    if (usersColumns.has('role') && role) {
      cols.push('role');
      vals.push(role);
    }
    if (usersColumns.has('metadata') && metadata && typeof metadata === 'object') {
      cols.push('metadata');
      vals.push(metadata);
    }

    const placeholders = vals.map((_, idx) => `$${idx + 1}`).join(', ');
    const query = `INSERT INTO users (${cols.join(', ')}) VALUES (${placeholders}) RETURNING *`;

    try {
      const result = await pool.query(query, vals);
      return new User(result.rows[0]);
    } catch (error) {
      if (error.code === '23505') { // Unique violation
        if (String(error.constraint || '').includes('email')) {
          throw new Error('Email already exists');
        } else if (String(error.constraint || '').includes('username')) {
          throw new Error('Username already exists');
        }
      }
      throw error;
    }
  }

  /**
   * Find user by email
   */
  static async findByEmail(email) {
    const query = 'SELECT * FROM users WHERE email = $1 AND is_active = true';
    const result = await pool.query(query, [email]);
    return result.rows[0] ? new User(result.rows[0]) : null;
  }

  /**
   * Find user by username
   */
  static async findByUsername(username) {
    const usersColumns = await getUsersColumns();
    if (!usersColumns.has('username')) {
      return null;
    }
    const query = 'SELECT * FROM users WHERE username = $1 AND is_active = true';
    const result = await pool.query(query, [username]);
    return result.rows[0] ? new User(result.rows[0]) : null;
  }

  /**
   * Find user by ID
   */
  static async findById(id) {
    const query = 'SELECT * FROM users WHERE id = $1 AND is_active = true';
    const result = await pool.query(query, [id]);
    return result.rows[0] ? new User(result.rows[0]) : null;
  }

  /**
   * List viewer sub-accounts managed by a parent user.
   */
  static async listViewersForParent(parentUserId) {
    const query = `
      SELECT *
      FROM users
      WHERE role = 'viewer'
        AND is_active = true
        AND COALESCE(metadata->>'parentUserId', '') = $1
      ORDER BY created_at DESC
    `;
    const result = await pool.query(query, [parentUserId]);
    return result.rows.map((row) => new User(row));
  }

  /**
   * Find a specific viewer sub-account owned by a parent user.
   */
  static async findViewerById(viewerUserId, parentUserId) {
    const query = `
      SELECT *
      FROM users
      WHERE id = $1
        AND role = 'viewer'
        AND is_active = true
        AND COALESCE(metadata->>'parentUserId', '') = $2
      LIMIT 1
    `;
    const result = await pool.query(query, [viewerUserId, parentUserId]);
    return result.rows[0] ? new User(result.rows[0]) : null;
  }

  /**
   * Update viewer sub-account scope/profile.
   */
  static async updateViewer(viewerUserId, parentUserId, updates = {}) {
    const existing = await User.findViewerById(viewerUserId, parentUserId);
    if (!existing) {
      throw new Error('Viewer not found');
    }

    const nextMetadata = {
      ...(existing.metadata || {}),
      ...(updates.metadata && typeof updates.metadata === 'object' ? updates.metadata : {}),
      parentUserId,
    };

    const values = [];
    const sets = [];
    let index = 1;

    if (updates.email !== undefined) {
      sets.push(`email = $${index++}`);
      values.push(String(updates.email).toLowerCase().trim());
    }
    if (updates.firstName !== undefined || updates.lastName !== undefined) {
      const firstName = updates.firstName ?? existing.firstName ?? '';
      const lastName = updates.lastName ?? existing.lastName ?? '';
      const name = [firstName, lastName].filter(Boolean).join(' ').trim() || existing.username;
      sets.push(`name = $${index++}`);
      values.push(name);
    }
    if (updates.password) {
      const usersColumns = await getUsersColumns();
      const passwordColumn = usersColumns.has('password_hash')
        ? 'password_hash'
        : (usersColumns.has('encrypted_password') ? 'encrypted_password' : null);
      if (!passwordColumn) {
        throw new Error('Unsupported users schema: missing password_hash/encrypted_password');
      }
      const passwordHash = await bcrypt.hash(updates.password, 10);
      sets.push(`${passwordColumn} = $${index++}`);
      values.push(passwordHash);
    }
    if (updates.metadata) {
      sets.push(`metadata = $${index++}`);
      values.push(nextMetadata);
    }
    if (updates.isActive !== undefined) {
      sets.push(`is_active = $${index++}`);
      values.push(Boolean(updates.isActive));
    }

    if (!sets.length) {
      return existing;
    }

    sets.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(viewerUserId, parentUserId);

    const query = `
      UPDATE users
      SET ${sets.join(', ')}
      WHERE id = $${index++}
        AND role = 'viewer'
        AND COALESCE(metadata->>'parentUserId', '') = $${index}
      RETURNING *
    `;
    const result = await pool.query(query, values);
    return result.rows[0] ? new User(result.rows[0]) : null;
  }

  /**
   * Verify password
   */
  async verifyPassword(password) {
    if (!this.passwordHash) return false;
    return await bcrypt.compare(password, this.passwordHash);
  }

  /**
   * Generate JWT token
   */
  generateToken() {
    const payload = {
      userId: this.id,
      email: this.email,
      username: this.username,
      role: this.role,
      tenant_id: this.tenantId,
      parent_user_id: this.parentUserId,
      viewer_scope: this.viewerScope,
    };

    const secret = process.env.JWT_SECRET || 'your-secret-key-change-in-production';
    const expiresIn = process.env.JWT_EXPIRES_IN || '7d';

    return jwt.sign(payload, secret, { expiresIn });
  }

  /**
   * Update last login
   */
  async updateLastLogin() {
    const usersColumns = await getUsersColumns();
    const col = usersColumns.has('last_login')
      ? 'last_login'
      : (usersColumns.has('last_sign_in_at') ? 'last_sign_in_at' : null);
    if (!col) return;
    const query = `UPDATE users SET ${col} = CURRENT_TIMESTAMP WHERE id = $1`;
    await pool.query(query, [this.id]);
    this.lastLogin = new Date();
  }

  /**
   * Create user session
   */
  async createSession(tokenHash, userAgent, ipAddress) {
    const sessionId = uuidv4();
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000); // 7 days

    const query = `
      INSERT INTO user_sessions (id, user_id, token_hash, expires_at, user_agent, ip_address)
      VALUES ($1, $2, $3, $4, $5, $6)
    `;

    await pool.query(query, [sessionId, this.id, tokenHash, expiresAt, userAgent, ipAddress]);
    return sessionId;
  }

  /**
   * Clear expired sessions
   */
  static async clearExpiredSessions() {
    const query = 'DELETE FROM user_sessions WHERE expires_at < CURRENT_TIMESTAMP';
    const result = await pool.query(query);
    return result.rowCount;
  }

  /**
   * Invalidate user session
   */
  static async invalidateSession(tokenHash) {
    const query = 'DELETE FROM user_sessions WHERE token_hash = $1';
    const result = await pool.query(query, [tokenHash]);
    return result.rowCount > 0;
  }

  /**
   * Update user profile
   */
  async updateProfile(updates) {
    const { firstName, lastName, email } = updates;
    const name = [firstName, lastName].filter(Boolean).join(' ').trim();
    const query = `
      UPDATE users
      SET name = $1, email = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $3
      RETURNING *
    `;

    const result = await pool.query(query, [name, email, this.id]);
    Object.assign(this, result.rows[0]);
    return this;
  }

  /**
   * Change password
   */
  async changePassword(newPassword) {
    const saltRounds = 10;
    const passwordHash = await bcrypt.hash(newPassword, saltRounds);

    const usersColumns = await getUsersColumns();
    const passwordColumn = usersColumns.has('password_hash')
      ? 'password_hash'
      : (usersColumns.has('encrypted_password') ? 'encrypted_password' : null);
    if (!passwordColumn) {
      throw new Error('Unsupported users schema: missing password_hash/encrypted_password');
    }

    const query = `
      UPDATE users
      SET ${passwordColumn} = $1, updated_at = CURRENT_TIMESTAMP
      WHERE id = $2
    `;

    await pool.query(query, [passwordHash, this.id]);
    this.passwordHash = passwordHash;
  }

  /**
   * Deactivate user
   */
  async deactivate() {
    const query = 'UPDATE users SET is_active = false, updated_at = CURRENT_TIMESTAMP WHERE id = $1';
    await pool.query(query, [this.id]);
    this.isActive = false;
  }

  /**
   * Get user's portfolios
   */
  async getPortfolios() {
    const query = 'SELECT * FROM portfolios WHERE user_id = $1 AND is_active = true ORDER BY created_at DESC';
    const result = await pool.query(query, [this.id]);
    return result.rows;
  }

  /**
   * Get user's alerts
   */
  async getAlerts(limit = 50, unreadOnly = false) {
    let query = 'SELECT * FROM alerts WHERE user_id = $1';
    const params = [this.id];

    if (unreadOnly) {
      query += ' AND is_read = false';
    }

    query += ' ORDER BY created_at DESC LIMIT $2';
    params.push(limit);

    const result = await pool.query(query, params);
    return result.rows;
  }

  /**
   * Mark alerts as read
   */
  async markAlertsRead(alertIds) {
    const query = 'UPDATE alerts SET is_read = true WHERE user_id = $1 AND id = ANY($2)';
    const result = await pool.query(query, [this.id, alertIds]);
    return result.rowCount;
  }

  /**
   * To JSON (for API responses)
   */
  toJSON() {
    return {
      id: this.id,
      tenantId: this.tenantId,
      parentUserId: this.parentUserId,
      email: this.email,
      username: this.username,
      firstName: this.firstName,
      lastName: this.lastName,
      role: this.role,
      emailVerified: this.emailVerified,
      isActive: this.isActive,
      viewerScope: this.viewerScope,
      lastLogin: this.lastLogin,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt
    };
  }

  /**
   * To public JSON (safe for client)
   */
  toPublicJSON() {
    return {
      id: this.id,
      tenantId: this.tenantId,
      parentUserId: this.parentUserId,
      email: this.email,
      username: this.username,
      firstName: this.firstName,
      lastName: this.lastName,
      role: this.role,
      viewerScope: this.viewerScope,
      lastLogin: this.lastLogin,
      createdAt: this.createdAt
    };
  }
}

// Helper functions
export const createUser = User.create;
export const findUserByEmail = User.findByEmail;
export const findUserByUsername = User.findByUsername;
export const findUserById = User.findById;
export const listViewerAccountsForParent = User.listViewersForParent;
export const findViewerAccountById = User.findViewerById;
export const updateViewerAccount = User.updateViewer;
