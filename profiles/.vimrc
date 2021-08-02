" Text entry related options
set autoindent
set expandtab
set shiftround
set smarttab
set shiftwidth=3
set tabstop=3
set softtabstop=3
set hlsearch
set smartcase
set mouse=a                 " All mouse options
set ttymouse=xterm2         " Mouse drag events
set wildmenu
set laststatus=2            " Always shoe last status
set backspace=2             " Backspace past eol and start of insert
set clipboard=autoselect    " Yanks stay on clipboard across vim sessions
set noerrorbells
set belloff=all

" Spell setup
syntax enable
set spell
set spellfile=~/.vim/spell/en.utf-8.add

" Visual display related options
colorscheme zellner
set display+=lastline
set encoding=utf-8
set linebreak
set scrolloff=1
set sidescrolloff=5
set wrap
set title
set number
set colorcolumn=80,100,120
hi ColorColumn ctermbg=grey guibg=grey
set noequalalways "Splits don't change window width
set ruler
set showcmd
set confirm
set showfulltag
highlight ExtraWhitespace ctermbg=red guibg=red
match ExtraWhitespace /\s\+$/
autocmd BufWinEnter * match ExtraWhitespace /\s\+$/
autocmd InsertEnter * match ExtraWhitespace /\s\+\%#\@<!$/
autocmd InsertLeave * match ExtraWhitespace /\s\+$/
autocmd BufWinLeave * call clearmatches()

" File options
set tabpagemax=50
set dir=~/.cache/vim
set formatoptions+=j
set history=1000
set tags+=tags;/
