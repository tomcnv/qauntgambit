/**
 * React Hooks for Bot Configuration Validation
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  validateConfig,
  validateBot,
  preflightCheck,
  validateConfigClient,
  type BotConfigForValidation,
  type ValidationResult,
  type PreflightResult,
} from './config-validation';

/**
 * Hook for real-time client-side validation as user edits config
 * Provides instant feedback without network requests
 */
export function useConfigValidation(config: BotConfigForValidation | null) {
  const validation = useMemo(() => {
    if (!config) {
      return {
        valid: true,
        errors: [],
        warnings: [],
        info: [],
        summary: 'No configuration'
      };
    }
    return validateConfigClient(config);
  }, [
    // Only re-validate when relevant fields change
    config?.tradingCapitalUsd,
    config?.enabledSymbols?.length,
    config?.tradingMode,
    config?.isDemo,
    config?.riskConfig?.positionSizePct,
    config?.riskConfig?.maxPositions,
    config?.riskConfig?.maxTotalExposurePct,
    config?.riskConfig?.maxExposurePerSymbolPct,
    config?.riskConfig?.maxLeverage,
    config?.riskConfig?.maxDailyLossPct,
    config?.executionConfig?.stopLossPct,
    config?.executionConfig?.takeProfitPct,
    config?.executionConfig?.trailingStopEnabled,
    config?.executionConfig?.trailingStopPct,
  ]);

  return validation;
}

/**
 * Hook for server-side validation (more comprehensive)
 * Use when you need to verify against backend rules
 */
export function useServerValidation(config: BotConfigForValidation | null, enabled = false) {
  return useQuery<ValidationResult>({
    queryKey: ['config-validation', config],
    queryFn: () => validateConfig(config!),
    enabled: enabled && !!config,
    staleTime: 5000, // Cache for 5 seconds
  });
}

/**
 * Hook for validating a saved bot's configuration
 */
export function useBotValidation(botId: string | null) {
  return useQuery<ValidationResult>({
    queryKey: ['bot-validation', botId],
    queryFn: () => validateBot(botId!),
    enabled: !!botId,
    staleTime: 30000, // Cache for 30 seconds
  });
}

/**
 * Hook for pre-flight check before starting a bot
 */
export function usePreflightCheck() {
  return useMutation<PreflightResult, Error, string>({
    mutationFn: (botId: string) => preflightCheck(botId),
  });
}

/**
 * Combined hook that provides both client-side and optional server validation
 * Best for forms where you want instant feedback + final server check
 */
export function useFormValidation(config: BotConfigForValidation | null) {
  // Client-side validation for instant feedback
  const clientValidation = useConfigValidation(config);
  
  // Track if we should do server validation
  const [serverValidationEnabled, setServerValidationEnabled] = useState(false);
  
  // Server validation (only when explicitly requested)
  const serverValidation = useServerValidation(config, serverValidationEnabled);
  
  // Trigger server validation
  const validateWithServer = useCallback(() => {
    setServerValidationEnabled(true);
  }, []);
  
  // Reset server validation state
  useEffect(() => {
    if (serverValidation.isSuccess || serverValidation.isError) {
      setServerValidationEnabled(false);
    }
  }, [serverValidation.isSuccess, serverValidation.isError]);
  
  return {
    // Instant client-side validation
    validation: clientValidation,
    
    // Server validation
    serverValidation: serverValidation.data,
    isValidatingServer: serverValidation.isLoading,
    serverError: serverValidation.error,
    
    // Trigger server validation
    validateWithServer,
    
    // Helper properties
    isValid: clientValidation.valid,
    hasErrors: clientValidation.errors.length > 0,
    hasWarnings: clientValidation.warnings.length > 0,
    errorCount: clientValidation.errors.length,
    warningCount: clientValidation.warnings.length,
  };
}

/**
 * Hook specifically for the "Start Bot" button flow
 */
export function useStartBotValidation(botId: string | null) {
  const preflight = usePreflightCheck();
  
  const checkCanStart = useCallback(async () => {
    if (!botId) {
      return {
        canStart: false,
        reason: 'No bot selected',
        errors: [{ id: 'no_bot', severity: 'error' as const, field: null, message: 'No bot selected' }],
        warnings: [],
        info: [],
        summary: '1 error'
      };
    }
    return preflight.mutateAsync(botId);
  }, [botId, preflight]);
  
  return {
    checkCanStart,
    result: preflight.data,
    isChecking: preflight.isPending,
    error: preflight.error,
    reset: preflight.reset,
  };
}




