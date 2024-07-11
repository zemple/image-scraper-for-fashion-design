import random

def print_board(board):
    for row in board:
        print(" | ".join(row))
        print("-" * 9)

def is_winner(board, player):
    for i in range(3):
        if all(board[i][j] == player for j in range(3)) or \
           all(board[j][i] == player for j in range(3)):
            return True
    return board[0][0] == board[1][1] == board[2][2] == player or \
           board[0][2] == board[1][1] == board[2][0] == player

def is_board_full(board):
    return all(board[i][j] != ' ' for i in range(3) for j in range(3))

def get_empty_cells(board):
    return [(i, j) for i in range(3) for j in range(3) if board[i][j] == ' ']

def evaluate(board):
    if is_winner(board, 'O'):
        return 1
    elif is_winner(board, 'X'):
        return -1
    else:
        return 0

def minimax_alpha_beta(board, depth, alpha, beta, is_maximizing):
    score = evaluate(board)
    
    if score != 0:
        return score
    
    if is_board_full(board):
        return 0
    
    if is_maximizing:
        best_score = float('-inf')
        for i, j in get_empty_cells(board):
            board[i][j] = 'O'
            score = minimax_alpha_beta(board, depth + 1, alpha, beta, False)
            board[i][j] = ' '
            best_score = max(score, best_score)
            alpha = max(alpha, best_score)
            if beta <= alpha:
                break
        return best_score
    else:
        best_score = float('inf')
        for i, j in get_empty_cells(board):
            board[i][j] = 'X'
            score = minimax_alpha_beta(board, depth + 1, alpha, beta, True)
            board[i][j] = ' '
            best_score = min(score, best_score)
            beta = min(beta, best_score)
            if beta <= alpha:
                break
        return best_score

def get_best_move(board):
    best_score = float('-inf')
    best_move = None
    alpha = float('-inf')
    beta = float('inf')
    for i, j in get_empty_cells(board):
        board[i][j] = 'O'
        score = minimax_alpha_beta(board, 0, alpha, beta, False)
        board[i][j] = ' '
        if score > best_score:
            best_score = score
            best_move = (i, j)
        alpha = max(alpha, best_score)
    return best_move

def play_game():
    board = [[' ' for _ in range(3)] for _ in range(3)]
    
    while True:
        print_board(board)
        
        # Player's turn
        while True:
            try:
                row, col = map(int, input("Enter your move (row and column): ").split())
                if board[row][col] == ' ':
                    board[row][col] = 'X'
                    break
                else:
                    print("That cell is already occupied. Try again.")
            except (ValueError, IndexError):
                print("Invalid input. Please enter row and column (0-2) separated by space.")
        
        if is_winner(board, 'X'):
            print_board(board)
            print("You win!")
            break
        
        if is_board_full(board):
            print_board(board)
            print("It's a tie!")
            break
        
        # AI's turn
        print("AI is making a move...")
        row, col = get_best_move(board)
        board[row][col] = 'O'
        
        if is_winner(board, 'O'):
            print_board(board)
            print("AI wins!")
            break
        
        if is_board_full(board):
            print_board(board)
            print("It's a tie!")
            break

if __name__ == "__main__":
    play_game()