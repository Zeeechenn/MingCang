import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

// 前端测试基建冒烟：验证 vitest + jsdom + @testing-library/react +
// jest-dom 匹配器 + tsx 整条链路可用。这是"前端零测试"补的第一根测试桩，
// 后续按路由/组件补真实用例。
function Hello({ name }: { name: string }) {
  return <div>Hello {name}</div>;
}

describe('frontend test harness smoke', () => {
  it('renders a component via @testing-library/react + jsdom', () => {
    render(<Hello name="明仓" />);
    expect(screen.getByText('Hello 明仓')).toBeInTheDocument();
  });
});
