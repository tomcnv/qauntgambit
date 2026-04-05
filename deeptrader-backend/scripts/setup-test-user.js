#!/usr/bin/env node
/**
 * Setup test user for API testing
 */

import axios from 'axios';

const API_BASE = 'http://localhost:3001/api';
const TEST_EMAIL = 'test@example.com';
const TEST_PASSWORD = 'testpassword123';

async function setupTestUser() {
  try {
    // Try to register
    console.log('📝 Registering test user...');
    const registerResponse = await axios.post(`${API_BASE}/auth/register`, {
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
      username: 'testuser',
      firstName: 'Test',
      lastName: 'User',
    });
    
    if (registerResponse.data.token) {
      console.log('✅ Test user created successfully');
      console.log(`   Email: ${TEST_EMAIL}`);
      console.log(`   Token: ${registerResponse.data.token.substring(0, 20)}...`);
      return registerResponse.data.token;
    }
  } catch (error) {
    if (error.response?.status === 409) {
      console.log('ℹ️  Test user already exists, trying to login...');
      
      // Try to login
      try {
        const loginResponse = await axios.post(`${API_BASE}/auth/login`, {
          email: TEST_EMAIL,
          password: TEST_PASSWORD,
        });
        
        if (loginResponse.data.token) {
          console.log('✅ Test user login successful');
          console.log(`   Token: ${loginResponse.data.token.substring(0, 20)}...`);
          return loginResponse.data.token;
        }
      } catch (loginError) {
        console.error('❌ Login failed:', loginError.response?.data || loginError.message);
        return null;
      }
    } else {
      console.error('❌ Registration failed:', error.response?.data || error.message);
      return null;
    }
  }
  
  return null;
}

setupTestUser().then(token => {
  if (token) {
    console.log('\n✅ Test user ready!');
    console.log(`\nYou can use this token for testing:`);
    console.log(`export JWT_TOKEN="${token}"`);
    process.exit(0);
  } else {
    console.log('\n❌ Failed to setup test user');
    process.exit(1);
  }
}).catch(console.error);





