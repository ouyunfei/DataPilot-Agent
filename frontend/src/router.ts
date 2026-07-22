import { createRouter, createWebHistory } from 'vue-router'

import AnalysisPage from './pages/AnalysisPage.vue'
import OverviewPage from './pages/OverviewPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/analysis' },
    { path: '/analysis', component: AnalysisPage, meta: { title: 'AI 问数' } },
    { path: '/overview', component: OverviewPage, meta: { title: '数据概览' } },
  ],
})
