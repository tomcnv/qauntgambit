import express from 'express';
import { authenticateToken } from '../middleware/auth.js';
import * as StrategyInstance from '../models/StrategyInstance.js';

const router = express.Router();
router.use(authenticateToken);

function resolveUserId(req) {
  return req?.user?.id || req?.user?.userId || null;
}

router.get('/', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const { status, templateId, includeSystemTemplates } = req.query;
    const instances = await StrategyInstance.getInstancesByUser(userId, {
      status: status || null,
      templateId: templateId || null,
      includeSystemTemplates: includeSystemTemplates === 'false' ? false : true,
    });
    res.json({ success: true, instances, count: instances.length });
  } catch (error) {
    console.error('Error fetching strategy instances:', error);
    res.status(500).json({ success: false, error: 'Failed to fetch strategy instances', message: error.message });
  }
});

router.get('/templates', async (req, res) => {
  try {
    const templates = await StrategyInstance.getSystemTemplates({ status: 'active' });
    res.json({ success: true, templates, count: templates.length });
  } catch (error) {
    console.error('Error fetching strategy templates:', error);
    res.status(500).json({ success: false, error: 'Failed to fetch strategy templates', message: error.message });
  }
});

router.get('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const id = req.params.id;
    const own = await StrategyInstance.getInstanceByIdAndUser(id, userId);
    const system = own ? null : await StrategyInstance.getSystemTemplates({ status: null }).then((rows) => rows.find((r) => r.id === id) || null);
    const instance = own || system;
    if (!instance) return res.status(404).json({ success: false, error: 'Strategy instance not found' });
    res.json({ success: true, instance });
  } catch (error) {
    console.error('Error fetching strategy instance:', error);
    res.status(500).json({ success: false, error: 'Failed to fetch strategy instance', message: error.message });
  }
});

router.get('/:id/usage', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const usage = await StrategyInstance.getInstanceUsage(req.params.id, userId);
    res.json({ success: true, ...usage });
  } catch (error) {
    const code = String(error?.message || '').includes('not found') ? 404 : 500;
    res.status(code).json({ success: false, error: 'Failed to fetch strategy usage', message: error.message });
  }
});

router.post('/', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const { templateId, name, description, params } = req.body || {};
    if (!templateId || !name) return res.status(400).json({ success: false, error: 'templateId and name are required' });
    const instance = await StrategyInstance.createInstance({ userId, templateId, name, description: description || null, params: params || {} });
    res.status(201).json({ success: true, instance });
  } catch (error) {
    res.status(500).json({ success: false, error: 'Failed to create strategy instance', message: error.message });
  }
});

router.put('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const instance = await StrategyInstance.updateInstance(req.params.id, userId, req.body || {});
    res.json({ success: true, instance });
  } catch (error) {
    const code = String(error?.message || '').includes('not found') ? 404 : 500;
    res.status(code).json({ success: false, error: 'Failed to update strategy instance', message: error.message });
  }
});

router.post('/:id/clone', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const instance = await StrategyInstance.cloneInstance(req.params.id, userId, req.body?.name || null);
    res.status(201).json({ success: true, instance });
  } catch (error) {
    res.status(400).json({ success: false, error: 'Failed to clone strategy instance', message: error.message });
  }
});

router.post('/:id/archive', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const instance = await StrategyInstance.archiveInstance(req.params.id, userId);
    res.json({ success: true, instance });
  } catch (error) {
    res.status(400).json({ success: false, error: 'Failed to archive strategy instance', message: error.message });
  }
});

router.post('/:id/deprecate', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const instance = await StrategyInstance.deprecateInstance(req.params.id, userId);
    res.json({ success: true, instance });
  } catch (error) {
    res.status(400).json({ success: false, error: 'Failed to deprecate strategy instance', message: error.message });
  }
});

router.post('/:id/restore', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const instance = await StrategyInstance.restoreInstance(req.params.id, userId);
    res.json({ success: true, instance });
  } catch (error) {
    res.status(400).json({ success: false, error: 'Failed to restore strategy instance', message: error.message });
  }
});

router.delete('/:id', async (req, res) => {
  try {
    const userId = resolveUserId(req);
    if (!userId) return res.status(401).json({ success: false, error: 'Authentication required' });
    const result = await StrategyInstance.deleteInstance(req.params.id, userId);
    res.json({ success: true, ...result });
  } catch (error) {
    res.status(400).json({ success: false, error: 'Failed to delete strategy instance', message: error.message });
  }
});

export default router;
