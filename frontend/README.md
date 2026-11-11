# 正式桌面工作台

Node 24.14.1及以上的24.x、React、TypeScript、Vite；数据只通过同源`/api`读取，生产包不含合成联系人。工作台／设置之外不新增导航页。

从项目根目录安装和构建：

```bash
npm --prefix frontend ci --engine-strict
npm --prefix frontend run build
```

从根目录启动后端时，Settings.load选择`frontend/dist`，静态资源和API由同一端口提供。Python wheel本身尚不捆绑前端，独立打包在M5交付。Mac完整命令见[验证指南](../docs/MAC_SETUP.md#13-m1任务5正式桌面页面与设置)。

开发模式：

```bash
WECHAT_API_URL=http://127.0.0.1:8766 npm --prefix frontend run dev
```

Vite默认代理127.0.0.1:8000，可用上述环境变量覆盖。浏览器只向页面同源地址请求，不把后端来源或模型凭据放进前端。

```bash
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npm run test:e2e -- contacts.spec.ts
```

E2E由Playwright启动独立FastAPI与Vite，使用临时SQLite／合成来源，逐用例复位、workers=1。`/api/__test__/reset`只在tests.webserver注册。默认使用Playwright浏览器；云端若下载被拦，可通过`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`明确选用已经安装的浏览器，不在配置里硬编码系统路径。

设计使用项目Apple参考和taste的控件／动效原则，桌面最小1120px。采用系统字体，正文14px，输入48px高／12px圆角，常规身份标签28px高。营销页hero、照片、手机适配和营销评分不适用于这个内部工作台。

模型、档案编辑和自动调度尚未实现，界面明确标记能力边界；不使用原型数据冒充真实档案。来源状态来自后端持久化任务，不做隐式网络探测。
