export default {
  content: ['./index.html','./src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: { primary:'#080C14', secondary:'#0D1420', card:'#111827', elevated:'#1a2234' },
        accent: { green:'#00FF88', red:'#FF3355', gold:'#FFB800', blue:'#0EA5FF', purple:'#8B5CF6' },
        border: { dim:'#1E2D45', bright:'#2A3F5A' }
      },
      fontFamily: {
        mono: ['JetBrains Mono','monospace'],
        display: ['Rajdhani','sans-serif'],
        body: ['DM Sans','sans-serif']
      }
    }
  },
  plugins: []
}
