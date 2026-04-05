import { Component, type ReactNode } from "react";

type AppErrorBoundaryProps = {
  children: ReactNode;
  fallback?: ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
};

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = {
    hasError: false,
    error: null,
  };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("App render error boundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
            <div className="w-full max-w-lg rounded-lg border border-destructive/30 bg-destructive/5 p-6">
              <h1 className="text-lg font-semibold">Application failed to render</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {this.state.error?.message || "An unexpected rendering error occurred."}
              </p>
              <button
                type="button"
                className="mt-4 rounded-md bg-destructive px-3 py-2 text-sm text-destructive-foreground"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                Retry
              </button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
