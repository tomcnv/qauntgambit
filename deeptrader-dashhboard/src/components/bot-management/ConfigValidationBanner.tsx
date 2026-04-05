/**
 * Configuration Validation Banner Component
 * 
 * Displays validation errors, warnings, and info for bot configuration.
 * Shows inline in the bot edit form and in pre-start dialogs.
 */

import React from 'react';
import { AlertCircle, AlertTriangle, Info, CheckCircle, ChevronDown, ChevronUp, Lightbulb } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ValidationResult, ValidationIssue } from '@/lib/api/config-validation';

interface ConfigValidationBannerProps {
  validation: ValidationResult | null;
  className?: string;
  showInfo?: boolean;
  collapsible?: boolean;
  defaultExpanded?: boolean;
}

export function ConfigValidationBanner({
  validation,
  className,
  showInfo = false,
  collapsible = false,
  defaultExpanded = true,
}: ConfigValidationBannerProps) {
  const [expanded, setExpanded] = React.useState(defaultExpanded);

  if (!validation) return null;

  const { errors, warnings, info, valid, summary } = validation;
  
  // Don't show anything if everything is valid and no warnings
  if (valid && warnings.length === 0 && (!showInfo || info.length === 0)) {
    return null;
  }

  const hasErrors = errors.length > 0;
  const hasWarnings = warnings.length > 0;
  const hasInfo = info.length > 0;

  // Determine overall status color
  const statusColor = hasErrors 
    ? 'border-destructive/50 bg-destructive/10' 
    : hasWarnings 
      ? 'border-yellow-500/50 bg-yellow-500/10' 
      : 'border-blue-500/50 bg-blue-500/10';

  const StatusIcon = hasErrors ? AlertCircle : hasWarnings ? AlertTriangle : Info;
  const statusIconColor = hasErrors ? 'text-destructive' : hasWarnings ? 'text-yellow-500' : 'text-blue-500';

  return (
    <div className={cn('rounded-lg border p-4', statusColor, className)}>
      {/* Header */}
      <div 
        className={cn(
          'flex items-center justify-between',
          collapsible && 'cursor-pointer'
        )}
        onClick={() => collapsible && setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <StatusIcon className={cn('h-5 w-5', statusIconColor)} />
          <span className="font-medium">
            {hasErrors ? 'Configuration Issues' : hasWarnings ? 'Configuration Warnings' : 'Configuration Info'}
          </span>
          <span className="text-sm text-muted-foreground">({summary})</span>
        </div>
        {collapsible && (
          <button className="text-muted-foreground hover:text-foreground">
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        )}
      </div>

      {/* Issues List */}
      {expanded && (
        <div className="mt-3 space-y-2">
          {/* Errors */}
          {errors.map((issue) => (
            <ValidationIssueItem key={issue.id} issue={issue} />
          ))}
          
          {/* Warnings */}
          {warnings.map((issue) => (
            <ValidationIssueItem key={issue.id} issue={issue} />
          ))}
          
          {/* Info (only if showInfo is true) */}
          {showInfo && info.map((issue) => (
            <ValidationIssueItem key={issue.id} issue={issue} />
          ))}
        </div>
      )}
    </div>
  );
}

interface ValidationIssueItemProps {
  issue: ValidationIssue;
}

function ValidationIssueItem({ issue }: ValidationIssueItemProps) {
  const [showDetail, setShowDetail] = React.useState(false);

  const IconComponent = issue.severity === 'error' 
    ? AlertCircle 
    : issue.severity === 'warning' 
      ? AlertTriangle 
      : Info;

  const iconColor = issue.severity === 'error'
    ? 'text-destructive'
    : issue.severity === 'warning'
      ? 'text-yellow-500'
      : 'text-blue-500';

  const bgColor = issue.severity === 'error'
    ? 'bg-destructive/5'
    : issue.severity === 'warning'
      ? 'bg-yellow-500/5'
      : 'bg-blue-500/5';

  return (
    <div className={cn('rounded-md p-3', bgColor)}>
      <div className="flex items-start gap-2">
        <IconComponent className={cn('h-4 w-4 mt-0.5 flex-shrink-0', iconColor)} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{issue.message}</p>
          
          {/* Field indicator */}
          {issue.field && (
            <p className="text-xs text-muted-foreground mt-1">
              Field: <code className="bg-muted px-1 py-0.5 rounded">{issue.field}</code>
            </p>
          )}
          
          {/* Detail (expandable) */}
          {issue.detail && (
            <button
              className="text-xs text-muted-foreground hover:text-foreground mt-1 flex items-center gap-1"
              onClick={() => setShowDetail(!showDetail)}
            >
              {showDetail ? 'Hide details' : 'Show details'}
              {showDetail ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
          )}
          
          {showDetail && issue.detail && (
            <p className="text-xs text-muted-foreground mt-2 pl-2 border-l-2 border-muted">
              {issue.detail}
            </p>
          )}
          
          {/* Suggestion */}
          {issue.suggestion && (
            <div className="flex items-start gap-1.5 mt-2 text-xs">
              <Lightbulb className="h-3.5 w-3.5 text-yellow-500 mt-0.5 flex-shrink-0" />
              <span className="text-muted-foreground">{issue.suggestion}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Compact validation indicator for headers/cards
 */
interface ValidationIndicatorProps {
  validation: ValidationResult | null;
  size?: 'sm' | 'md';
}

export function ValidationIndicator({ validation, size = 'md' }: ValidationIndicatorProps) {
  if (!validation) return null;

  const { errors, warnings, valid } = validation;
  
  if (valid && warnings.length === 0) {
    return (
      <div className="flex items-center gap-1 text-green-500">
        <CheckCircle className={cn('h-4 w-4', size === 'sm' && 'h-3 w-3')} />
        {size !== 'sm' && <span className="text-xs">Valid</span>}
      </div>
    );
  }

  if (errors.length > 0) {
    return (
      <div className="flex items-center gap-1 text-destructive">
        <AlertCircle className={cn('h-4 w-4', size === 'sm' && 'h-3 w-3')} />
        <span className="text-xs">{errors.length} error{errors.length > 1 ? 's' : ''}</span>
      </div>
    );
  }

  if (warnings.length > 0) {
    return (
      <div className="flex items-center gap-1 text-yellow-500">
        <AlertTriangle className={cn('h-4 w-4', size === 'sm' && 'h-3 w-3')} />
        <span className="text-xs">{warnings.length} warning{warnings.length > 1 ? 's' : ''}</span>
      </div>
    );
  }

  return null;
}

/**
 * Pre-start dialog content showing validation results
 */
interface PreStartValidationProps {
  canStart: boolean;
  reason: string;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  suggestedFixes?: Record<string, unknown>;
}

export function PreStartValidation({
  canStart,
  reason,
  errors,
  warnings,
  suggestedFixes,
}: PreStartValidationProps) {
  if (canStart && warnings.length === 0) {
    return (
      <div className="flex items-center gap-3 p-4 rounded-lg bg-green-500/10 border border-green-500/30">
        <CheckCircle className="h-6 w-6 text-green-500" />
        <div>
          <p className="font-medium text-green-700 dark:text-green-400">Ready to Start</p>
          <p className="text-sm text-muted-foreground">Configuration validated successfully</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Main status */}
      <div className={cn(
        'flex items-center gap-3 p-4 rounded-lg border',
        canStart 
          ? 'bg-yellow-500/10 border-yellow-500/30' 
          : 'bg-destructive/10 border-destructive/30'
      )}>
        {canStart ? (
          <AlertTriangle className="h-6 w-6 text-yellow-500" />
        ) : (
          <AlertCircle className="h-6 w-6 text-destructive" />
        )}
        <div>
          <p className={cn(
            'font-medium',
            canStart ? 'text-yellow-700 dark:text-yellow-400' : 'text-destructive'
          )}>
            {canStart ? 'Review Warnings Before Starting' : 'Cannot Start Bot'}
          </p>
          <p className="text-sm text-muted-foreground">{reason}</p>
        </div>
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-destructive">
            Errors ({errors.length})
          </h4>
          {errors.map((error) => (
            <ValidationIssueItem key={error.id} issue={error} />
          ))}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-yellow-600 dark:text-yellow-400">
            Warnings ({warnings.length})
          </h4>
          {warnings.map((warning) => (
            <ValidationIssueItem key={warning.id} issue={warning} />
          ))}
        </div>
      )}

      {/* Suggested fixes */}
      {suggestedFixes && Object.keys(suggestedFixes).length > 0 && (
        <div className="p-3 rounded-lg bg-muted/50 border">
          <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
            <Lightbulb className="h-4 w-4 text-yellow-500" />
            Suggested Fixes
          </h4>
          <ul className="text-sm text-muted-foreground space-y-1">
            {Object.entries(suggestedFixes).map(([key, value]) => (
              <li key={key}>
                Set <code className="bg-muted px-1 rounded">{key}</code> to{' '}
                <code className="bg-muted px-1 rounded">{String(value)}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ConfigValidationBanner;




