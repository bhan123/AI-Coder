import { defineConfig } from '@tarojs/cli';

export default defineConfig({
  projectName: 'love-fueling-station-miniprogram',
  date: '2026-08-20',
  designWidth: 390,
  deviceRatio: {
    390: 1,
    375: 1,
    750: 2,
  },
  sourceRoot: 'src',
  outputRoot: process.env.TARO_ENV === 'h5' ? 'dist-h5' : 'dist',
  framework: 'react',
  compiler: 'webpack5',
  plugins: ['@tarojs/plugin-platform-h5'],
  mini: {},
  h5: {
    staticDirectory: 'static',
  },
});
