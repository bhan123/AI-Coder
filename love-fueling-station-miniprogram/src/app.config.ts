export default defineAppConfig({
  pages: [
    'pages/home/index',
    'pages/record/index',
    'pages/history/index',
    'pages/agreements/index',
    'pages/pair/index',
    'pages/privacy/index',
    'pages/operations/index',
  ],
  window: {
    navigationBarBackgroundColor: '#fffaf3',
    navigationBarTextStyle: 'black',
    navigationBarTitleText: '爱意存折',
    backgroundColor: '#fffaf3',
    backgroundTextStyle: 'dark',
  },
  tabBar: {
    color: '#82766d',
    selectedColor: '#ef5943',
    backgroundColor: '#fffdf9',
    borderStyle: 'white',
    list: [
      { pagePath: 'pages/home/index', text: '首页' },
      { pagePath: 'pages/record/index', text: '记录' },
      { pagePath: 'pages/history/index', text: '我们' },
      { pagePath: 'pages/agreements/index', text: '约定' }
    ]
  },
});
