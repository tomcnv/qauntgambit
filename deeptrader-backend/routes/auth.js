/**
 * Authentication Routes
 * User registration, login, and session management
 */

import express from 'express';
import bcrypt from 'bcrypt';
import crypto from 'crypto';
import { createUser, findUserByEmail, findUserByUsername, findUserById } from '../models/User.js';
import { authenticateToken, rateLimit } from '../middleware/auth.js';

const router = express.Router();

// Rate limiting for auth endpoints
// Disable in development or if explicitly disabled
const AUTH_RATE_LIMIT_DISABLED =
  process.env.AUTH_RATE_LIMIT_DISABLED === 'true' || 
  process.env.NODE_ENV !== 'production' ||
  !process.env.NODE_ENV; // Also disable if NODE_ENV is not set

const passthroughLimiter = (_req, _res, next) => next();
// More lenient rate limit: 20 requests per 15 minutes (or disabled in dev)
const authRateLimit = AUTH_RATE_LIMIT_DISABLED 
  ? passthroughLimiter 
  : rateLimit(15 * 60 * 1000, 20); // 20 requests per 15 minutes in production

if (AUTH_RATE_LIMIT_DISABLED) {
  console.log('⚙️  Auth rate limiting disabled (development mode)');
} else {
  console.log('⚙️  Auth rate limiting enabled: 20 requests per 15 minutes');
}

/**
 * POST /api/auth/register
 * Register a new user
 * Accepts optional metadata JSONB for enterprise fields (company, firmType, aum, etc.)
 */
router.post('/register', authRateLimit, async (req, res) => {
  try {
    const { email, username, password, firstName, lastName, metadata } = req.body;

    // Validation
    if (!email || !password) {
      return res.status(400).json({
        error: 'Email and password are required'
      });
    }

    if (password.length < 8) {
      return res.status(400).json({
        error: 'Password must be at least 8 characters long'
      });
    }

    // Create user
    const user = await createUser({
      email: email.toLowerCase().trim(),
      // username is optional; the model will derive one from email when needed
      username: username?.trim(),
      password,
      firstName: firstName?.trim(),
      lastName: lastName?.trim()
    });

    // Generate token
    const token = user.generateToken();

    // Update last login
    await user.updateLastLogin();

    // Create portfolio for new user
    const { createPortfolio } = await import('../models/Portfolio.js');
    await createPortfolio(user.id, {
      name: 'Main Portfolio',
      description: 'Your primary trading portfolio',
      startingCapital: 10000.00,
      isPaperTrading: true
    });

    res.status(201).json({
      message: 'User created successfully',
      user: user.toPublicJSON(),
      token
    });

  } catch (error) {
    console.error('Registration error:', error);

    if (error.message.includes('already exists')) {
      return res.status(409).json({ error: error.message });
    }

    res.status(500).json({ error: 'Registration failed' });
  }
});

/**
 * POST /api/auth/login
 * User login
 */
router.post('/login', authRateLimit, async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({
        error: 'Email and password are required'
      });
    }

    // Find user by email or username
    let user = await findUserByEmail(email.toLowerCase().trim());
    if (!user) {
      user = await findUserByUsername(email.trim());
    }

    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    // Verify password
    const isValidPassword = await user.verifyPassword(password);
    if (!isValidPassword) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    // Check if user is active
    if (!user.isActive) {
      return res.status(401).json({ error: 'Account is deactivated' });
    }

    // Generate token
    const token = user.generateToken();

    // Update last login
    await user.updateLastLogin();

    // Create session record (optional)
    if (process.env.CHECK_SESSIONS === 'true') {
      const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
      await user.createSession(tokenHash, req.headers['user-agent'], req.ip);
    }

    res.json({
      message: 'Login successful',
      user: user.toPublicJSON(),
      token
    });

  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ error: 'Login failed' });
  }
});

/**
 * POST /api/auth/logout
 * User logout
 */
router.post('/logout', authenticateToken, async (req, res) => {
  try {
    // Invalidate session if sessions are enabled
    if (process.env.CHECK_SESSIONS === 'true') {
      const token = req.headers['authorization'].split(' ')[1];
      const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
      await req.user.constructor.invalidateSession(tokenHash);
    }

    res.json({ message: 'Logout successful' });
  } catch (error) {
    console.error('Logout error:', error);
    res.status(500).json({ error: 'Logout failed' });
  }
});

/**
 * GET /api/auth/me
 * Get current user profile
 */
router.get('/me', authenticateToken, async (req, res) => {
  try {
    const user = await findUserById(req.user.id);
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    res.json({ user: user.toPublicJSON() });
  } catch (error) {
    console.error('Get profile error:', error);
    res.status(500).json({ error: 'Failed to get profile' });
  }
});

/**
 * PUT /api/auth/profile
 * Update user profile
 */
router.put('/profile', authenticateToken, async (req, res) => {
  try {
    const { firstName, lastName, email } = req.body;

    // Basic validation
    if (email && (!email.includes('@') || email.length < 5)) {
      return res.status(400).json({ error: 'Invalid email format' });
    }

    const updates = {};
    if (firstName !== undefined) updates.firstName = firstName;
    if (lastName !== undefined) updates.lastName = lastName;
    if (email !== undefined) updates.email = email.toLowerCase().trim();

    const updatedUser = await req.user.updateProfile(updates);

    res.json({
      message: 'Profile updated successfully',
      user: updatedUser.toPublicJSON()
    });

  } catch (error) {
    console.error('Update profile error:', error);

    if (error.message.includes('already exists')) {
      return res.status(409).json({ error: error.message });
    }

    res.status(500).json({ error: 'Failed to update profile' });
  }
});

/**
 * PUT /api/auth/password
 * Change user password
 */
router.put('/password', authenticateToken, async (req, res) => {
  try {
    const { currentPassword, newPassword } = req.body;

    if (!currentPassword || !newPassword) {
      return res.status(400).json({
        error: 'Current password and new password are required'
      });
    }

    if (newPassword.length < 8) {
      return res.status(400).json({
        error: 'New password must be at least 8 characters long'
      });
    }

    // Verify current password
    const isCurrentPasswordValid = await req.user.verifyPassword(currentPassword);
    if (!isCurrentPasswordValid) {
      return res.status(400).json({ error: 'Current password is incorrect' });
    }

    // Change password
    await req.user.changePassword(newPassword);

    res.json({ message: 'Password changed successfully' });

  } catch (error) {
    console.error('Change password error:', error);
    res.status(500).json({ error: 'Failed to change password' });
  }
});

/**
 * POST /api/auth/forgot-password
 * Request password reset
 */
router.post('/forgot-password', authRateLimit, async (req, res) => {
  try {
    const { email } = req.body;

    if (!email) {
      return res.status(400).json({ error: 'Email is required' });
    }

    const user = await findUserByEmail(email.toLowerCase().trim());
    if (!user) {
      // Don't reveal if email exists for security
      return res.json({ message: 'If the email exists, a reset link has been sent' });
    }

    // Generate reset token
    const resetToken = crypto.randomBytes(32).toString('hex');
    const resetTokenHash = crypto.createHash('sha256').update(resetToken).digest('hex');
    const expiresAt = new Date(Date.now() + 60 * 60 * 1000); // 1 hour

    // TODO: Store resetTokenHash and expiresAt in database for user
    // TODO: Send email with resetToken (not the hash) to user
    // For now, this is a no-op placeholder - token is generated but not persisted or emailed

    res.json({ message: 'If the email exists, a reset link has been sent' });

  } catch (error) {
    console.error('Forgot password error:', error);
    res.status(500).json({ error: 'Failed to process request' });
  }
});

/**
 * POST /api/auth/reset-password
 * Reset password with token
 */
router.post('/reset-password', async (req, res) => {
  try {
    const { token, newPassword } = req.body;

    if (!token || !newPassword) {
      return res.status(400).json({
        error: 'Reset token and new password are required'
      });
    }

    if (newPassword.length < 8) {
      return res.status(400).json({
        error: 'Password must be at least 8 characters long'
      });
    }

    // Verify token (simplified - in real app, check database)
    const tokenHash = crypto.createHash('sha256').update(token).digest('hex');

    // TODO: Look up user by tokenHash and verify expiresAt > now
    // TODO: Update user password and clear the reset token

    res.json({ message: 'Password reset successfully' });

  } catch (error) {
    console.error('Reset password error:', error);
    res.status(500).json({ error: 'Failed to reset password' });
  }
});

/**
 * DELETE /api/auth/account
 * Delete user account
 */
router.delete('/account', authenticateToken, async (req, res) => {
  try {
    await req.user.deactivate();

    res.json({ message: 'Account deactivated successfully' });

  } catch (error) {
    console.error('Delete account error:', error);
    res.status(500).json({ error: 'Failed to delete account' });
  }
});

export default router;
