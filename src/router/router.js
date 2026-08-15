import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from './../components/chat/ChatPage.vue'

const routes = [
  { path: '/', name: 'chat', component: ChatPage },
  { path: '/:catchAll(.*)', redirect: { name: 'chat' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
