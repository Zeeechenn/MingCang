// 历史兼容层：原型代码把模块导出挂在 window 上（boot.ts / 各模块尾部的
// Object.assign(window, ...)）。模块间引用已改为真正的 import/export，
// window 挂载仅为运行时兼容保留。新代码请走 import，不要再读这些全局属性。
interface Window {
  React: any;
  ReactDOM: any;
  MC_DATA: any;
  MC_LIVE: any;
  MC_WIZ_KEY: string;
  MCStore: any;
  toast: any;
  HomePage: any;
  ChatPage: any;
  AdminPage: any;
  StockPage: any;
  StocksPage: any;
  PositionsPage: any;
  PulsePage: any;
  HealthPage: any;
  MemoryEvolutionPage: any;
  NewsShadowPage: any;
}
