大幅修改本程式TUI互動邏輯：
1.底端列不顯示目前的說明。
2.在任何畫面按:輸入指令模式(類似vim)，指令如下：
:q 結束程式(Y/n)
:Q 直接結束程式
:strong 切換為Strong模式，並跳至本章節，如果在非章節內使用則跳至目錄
:S 同:strong
:recovery 切換至恢復本，原理同:strong
:R 同:recovery
:strong genesis 1 1 切換至Strong模式，並跳至特定章節(參數可只給部分，例如:strong 1跳至本章1節／:strong 1 1跳至本卷1章1節)
:recovery genesis 1 1 切換至恢復本，原理同:strong
:1 可改數字，跳至本章該節
:1 1 可改數字，跳至本卷章節
:genesis 1 1 跳至指定卷章節
:footnote 顯示本節註解
:F =:footnote
:footnote 1 跳至本章特定節數並顯示其註解
:footnote 1 1跳至本卷特定章節並顯示註解
:footnote genesis 1 1 跳至指定書卷章節並顯示其註解
:intro 顯示本卷的書介(在恢復本的資料庫裡)
:copy 複製當前經文
:C =:copy
:copy 1 3-5 7 複製本章指定經文，用x-y指定連續的經節，用x y指定不連續的經節
:copy #1 複製本章指定經節的註解
:copy自動適配Termux/Ubuntu/Mac/Windows的剪貼簿，找不到時改存到使用者家目錄(如果寫入被允許)
:english on/off 開/關英文對照，不帶參數則直接切換
:E =:english
:outline on/off 開/關綱目及註解顯示，不帶參數則直接切換
:O =:outline
:search 基督 在當前經文版本查詢指定字串，多字串採聯集查詢，不捨結果數上限
:S =:search
:search -e Christ 在英文經文查詢指定字串，規則同:search
搜尋指令也可以後接--exclude以進行差集查詢，完整指令如:search [-e] arg1 arg2 ... [--exclude exarg1 exarg2 ...]，查詢(arg的聯集)和(exarg的聯集)的差集
:help 顯示：新舊約書卷中英對照表、本程式指令表。

3.在一般模式裡(不按:)，可按q/Q結束程式(行為同:q/:Q)，可按B/b回到上一頁(根據線性的頁面紀錄，包括模式的變更也應記入)

4.程式預設不寫入儲存空間，但使用者執行 :setup-storage 則可啟用以下指令：
:option 進入設定模式，設定項有資料庫檔案路徑(recovery/strong分別指定)、預設啟動恢復本或Strong、預設是否啟用中英對照和綱目註解、接下來提到的.bible-note.db的路徑檔名；設定檔存入.bible-note.db。
:option reset 重設所有設定(Y/n)
一般模式下按o/O =:option
:note 對當前經節做筆記，開啟編輯器如nano，儲存到.bible-note.db
:N =:note
:note 1 對本章指定經節做筆記
:note 1 1 對本卷指定章節做筆記
:note genesis 1 1 對指定卷章節做筆記
:note show 顯示當前經節的筆記，後接參數規則同:note
:bookmark 將當前經節加入書籤，一樣存到.bible-note.db
:M =:mark =:bookmark
:bookmark show 顯示所有已儲存的書籤經節出處和內容
:reference 1 為當前經節加上至本章指定經節的串珠，串珠也存在.bible-note.db，依序顯示在該節後面為a,b,...，點擊則跳到串珠的章節
:R =:reference
也可以:reference 1 1 或 :reference genesis 1 1 參數的原則從一而終
:reference也可以一次帶兩個經節作為參數，即在第一個參數的經節加上指向第二個經節的串珠，惟此時兩節格式都必須如genesis 1 1

5.其餘邏輯和相容性保持與原程式相同
