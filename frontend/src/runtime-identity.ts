import packageInfo from '../package.json';

export const FRONTEND_RUNTIME_IDENTITY = {
  version: packageInfo.version,
  buildCommit: import.meta.env.VITE_BUILD_COMMIT || 'unknown',
};

export interface BackendRuntimeIdentity {
  version?: string;
  build_commit?: string;
  db_role?: string;
  db_latest_date?: string | null;
  scheduler_mode?: string;
  database_exists?: boolean;
}

export interface RuntimeCompatibility {
  compatible: boolean;
  issues: string[];
  frontend: typeof FRONTEND_RUNTIME_IDENTITY;
  backend: BackendRuntimeIdentity | null;
}

export function assessBackendRuntime(
  status: BackendRuntimeIdentity | null | undefined,
): RuntimeCompatibility {
  const issues: string[] = [];
  if (!status) {
    issues.push('后端未返回运行身份');
    return {
      compatible: false,
      issues,
      frontend: FRONTEND_RUNTIME_IDENTITY,
      backend: null,
    };
  }

  if (!status.version) {
    issues.push('后端缺少版本号');
  } else if (status.version !== FRONTEND_RUNTIME_IDENTITY.version) {
    issues.push(`前后端版本不一致：前端 ${FRONTEND_RUNTIME_IDENTITY.version} / 后端 ${status.version}`);
  }

  if (!status.db_role) {
    issues.push('后端缺少数据库角色');
  } else if (status.db_role !== 'primary') {
    issues.push(`当前数据库角色为 ${status.db_role}，不是 primary`);
  }
  if (status.database_exists === false) issues.push('配置的数据库文件不存在');
  if (status.db_latest_date == null) issues.push('数据库没有最新交易日');
  if (!status.scheduler_mode) issues.push('后端缺少调度模式');

  const frontendCommit = FRONTEND_RUNTIME_IDENTITY.buildCommit;
  const backendCommit = status.build_commit || 'unknown';
  if (
    frontendCommit !== 'unknown'
    && backendCommit !== 'unknown'
    && frontendCommit !== backendCommit
  ) {
    issues.push(`前后端提交不一致：前端 ${frontendCommit} / 后端 ${backendCommit}`);
  }

  return {
    compatible: issues.length === 0,
    issues,
    frontend: FRONTEND_RUNTIME_IDENTITY,
    backend: status,
  };
}
